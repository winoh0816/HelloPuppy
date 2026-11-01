"""Guardian-held veterinary health record (PHR) helpers.

국내 동물병원 EMR(인투벳·이프렌즈·플러스벳 등)은 업체별 독자 형식이라 병원 간 직접 연동 표준이 없다.
그래서 보호자가 기록을 보관하고, 병원별 기한부 공유 링크와 HL7 FHIR R4 묶음(Bundle)으로
다른 병원에 전달하는 "보호자 중개형" 방식으로 구성한다.

항목 구성 근거
- 수의사법 시행규칙 제13조 진료부 기재사항: 품종·성별·특징·연령, 소유자, 진료일, 병명·주요 증상,
  처방·처치, 동물등록번호
- 진료 기록 SOAP 형식과 소동물 문진(병력 청취) 체크리스트: 주 증상, 계통별 문진, 식이, 예방, 약, 생활환경
- WSAVA 영양 평가: 사료·급여량·간식·영양제·식이 변경, 체중, 체형점수(BCS 9점)
- 농림축산식품부 「동물 진료의 권장 표준」 질병명·코드(선택 입력)
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import date
from html import escape
from typing import Any

SPECIES = {"dog", "cat", "other"}
REGISTRATION_TYPES = {"", "internal", "external", "none"}
LIVING_ENVIRONMENTS = {"", "indoor", "outdoor", "both"}
SHARE_SCOPES = {"read", "read_write"}

TEXT_LIMIT = 1000
SEVERITY = {"mild", "moderate", "severe"}
ROUTES = {"oral", "topical", "eye_ear", "injection", "other"}

# 기록 종류별 상세 필드. 값이 set이면 선택지, int면 최대 길이, tuple이면 (최소, 최대) 숫자 범위.
RECORD_TYPES: dict[str, dict[str, Any]] = {
    "visit": {
        "required": (),
        "fields": {
            "reason": TEXT_LIMIT, "subjective": TEXT_LIMIT, "findings": TEXT_LIMIT,
            "diagnosis": TEXT_LIMIT, "diagnosis_code": 40, "treatment": TEXT_LIMIT,
            "prescription": TEXT_LIMIT, "tests": TEXT_LIMIT, "vet_name": 80, "next_visit_date": 10,
        },
    },
    "vaccination": {
        "required": ("vaccine_type",),
        "fields": {
            "vaccine_type": {"dhppl", "corona", "kennel_cough", "influenza", "rabies", "other"},
            "product": 160, "dose_number": 20, "next_due_date": 10, "vet_name": 80,
        },
    },
    "parasite": {
        "required": ("parasite_type",),
        "fields": {
            "parasite_type": {"heartworm", "external", "internal", "combined"},
            "product": 160, "route": ROUTES, "next_due_date": 10,
        },
    },
    "medication": {
        "required": ("drug_name",),
        "fields": {
            "drug_name": 160, "dose": 80, "frequency": 80, "route": ROUTES, "purpose": 300,
            "start_date": 10, "end_date": 10, "medication_status": {"active", "stopped"},
        },
    },
    "condition": {
        "required": ("condition_name",),
        "fields": {
            "condition_name": 200, "diagnosis_code": 40, "diagnosed_date": 10,
            "condition_status": {"active", "resolved", "suspected"},
        },
    },
    "allergy": {
        "required": ("substance",),
        "fields": {
            "allergy_category": {"medication", "vaccine", "food", "environment", "other"},
            "substance": 200, "reaction": 500, "severity": SEVERITY,
        },
    },
    "surgery": {
        "required": ("procedure",),
        "fields": {
            "procedure": 200, "anesthesia": {"general", "sedation", "local", "none"},
            "anesthesia_reaction": 500,
        },
    },
    "lab": {
        "required": ("test_name",),
        "fields": {"test_name": 200, "result_summary": TEXT_LIMIT, "abnormal_findings": TEXT_LIMIT},
    },
    "weight": {
        "required": ("weight_kg",),
        "fields": {"weight_kg": (0.05, 150.0), "body_condition_score": (1, 9)},
    },
    "symptom": {
        "required": ("symptom",),
        "fields": {"symptom": 300, "duration": 100, "severity": SEVERITY},
    },
    "other": {"required": (), "fields": {}},
}

# 소동물 문진에서 계통별로 확인하는 항목
QUESTIONNAIRE_SYSTEMS = (
    "energy", "appetite", "water", "urination", "stool", "vomiting", "respiratory",
    "breathing", "skin", "eyes_ears", "mobility", "weight_change", "behavior",
)
SYSTEM_VALUES = {"", "normal", "increased", "decreased", "abnormal", "unknown"}
PROGRESSIONS = {"", "better", "same", "worse", "fluctuating"}


class HealthValidationError(ValueError):
    """Raised with a user-facing Korean message when submitted health data is invalid."""


def validate_iso_date(value: str, label: str) -> str:
    if not value:
        return ""
    try:
        date.fromisoformat(value)
    except ValueError as error:
        raise HealthValidationError(f"{label}은(는) YYYY-MM-DD 형식이어야 합니다.") from error
    return value


def validate_choice(value: str, choices: set[str], label: str) -> str:
    if value not in choices:
        raise HealthValidationError(f"{label} 값이 올바르지 않습니다.")
    return value


def validate_details(record_type: str, details: dict[str, Any]) -> dict[str, Any]:
    schema = RECORD_TYPES.get(record_type)
    if schema is None:
        raise HealthValidationError("지원하지 않는 기록 종류입니다.")
    unknown = set(details) - set(schema["fields"])
    if unknown:
        raise HealthValidationError(f"알 수 없는 항목입니다: {', '.join(sorted(unknown))}")
    cleaned: dict[str, Any] = {}
    for key, rule in schema["fields"].items():
        raw = details.get(key)
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            continue
        if isinstance(rule, tuple):
            try:
                number = float(raw)
            except (TypeError, ValueError) as error:
                raise HealthValidationError(f"{key} 값은 숫자여야 합니다.") from error
            if not rule[0] <= number <= rule[1]:
                raise HealthValidationError(f"{key} 값은 {rule[0]}~{rule[1]} 범위여야 합니다.")
            cleaned[key] = int(number) if isinstance(rule[0], int) else round(number, 2)
            continue
        value = str(raw).strip()
        if isinstance(rule, set):
            cleaned[key] = validate_choice(value, rule, key)
        elif key.endswith("_date"):
            cleaned[key] = validate_iso_date(value, key)
        else:
            if len(value) > rule:
                raise HealthValidationError(f"{key} 항목은 {rule}자 이하로 입력하세요.")
            cleaned[key] = value
    missing = [key for key in schema["required"] if key not in cleaned]
    if missing:
        raise HealthValidationError("필수 항목을 입력하세요: " + ", ".join(missing))
    return cleaned


def validate_systems(systems: dict[str, Any]) -> dict[str, str]:
    unknown = set(systems) - set(QUESTIONNAIRE_SYSTEMS)
    if unknown:
        raise HealthValidationError("알 수 없는 문진 항목입니다.")
    cleaned = {}
    for key in QUESTIONNAIRE_SYSTEMS:
        value = str(systems.get(key) or "").strip()
        validate_choice(value, SYSTEM_VALUES, key)
        if value:
            cleaned[key] = value
    return cleaned


def record_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    record = dict(row)
    try:
        record["details"] = json.loads(record.pop("details_json", None) or "{}")
    except json.JSONDecodeError:
        record["details"] = {}
    return record


def questionnaire_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    try:
        item["systems"] = json.loads(item.pop("systems_json", None) or "{}")
    except json.JSONDecodeError:
        item["systems"] = {}
    return item


def build_summary(db: sqlite3.Connection, user_id: int, activity_cutoff: str) -> dict[str, Any]:
    """Collect everything a clinic needs from the guardian into one payload."""
    pet = db.execute("SELECT * FROM pets WHERE user_id=?", (user_id,)).fetchone()
    pet_dict = dict(pet) if pet else {}
    pet_dict.pop("user_id", None)
    pet_dict["birth_date_estimated"] = bool(pet_dict.get("birth_date_estimated"))
    food = db.execute("SELECT f.* FROM food_profiles f JOIN pets p ON p.id=f.pet_id WHERE p.user_id=?", (user_id,)).fetchone()
    records = db.execute(
        "SELECT * FROM health_records WHERE user_id=? ORDER BY record_date DESC,id DESC", (user_id,)
    ).fetchall()
    questionnaires = db.execute(
        "SELECT * FROM pre_visit_questionnaires WHERE user_id=? ORDER BY visit_date DESC,id DESC LIMIT 5", (user_id,)
    ).fetchall()
    activity = db.execute(
        "SELECT activity,created_at FROM activity_logs WHERE user_id=? AND status='verified' AND created_at>=? ORDER BY id DESC",
        (user_id, activity_cutoff),
    ).fetchall()
    return {
        "pet": pet_dict,
        "food": dict(food) if food else {},
        "records": [record_row_to_dict(row) for row in records],
        "questionnaires": [questionnaire_row_to_dict(row) for row in questionnaires],
        "activity": [dict(row) for row in activity],
    }


# ---------------------------------------------------------------------------
# HL7 FHIR R4 변환
# ---------------------------------------------------------------------------

_FHIR_NAMESPACE = uuid.UUID("6f1c2f0e-7a51-4c55-9f1e-2a4c8b1d9e10")
SPECIES_CODING = {
    "dog": {"system": "http://snomed.info/sct", "code": "448771007", "display": "Canis lupus subsp. familiaris"},
    "cat": {"system": "http://snomed.info/sct", "code": "448169003", "display": "Felis catus"},
}
SPECIES_LABELS = {"dog": "개", "cat": "고양이", "other": "기타"}
VACCINE_LABELS = {
    "dhppl": "종합백신(DHPPL)", "corona": "코로나 장염", "kennel_cough": "켄넬코프",
    "influenza": "개 인플루엔자", "rabies": "광견병", "other": "기타 백신",
}
PARASITE_LABELS = {"heartworm": "심장사상충 예방", "external": "외부기생충 예방", "internal": "내부 구충", "combined": "복합 기생충 예방"}
ROUTE_LABELS = {"oral": "경구", "topical": "외용", "eye_ear": "점안·점이", "injection": "주사", "other": "기타"}
ALLERGY_CATEGORIES = {"medication": "medication", "food": "food", "environment": "environment", "vaccine": "biologic"}
SOURCE_SYSTEM = "urn:hellopuppy:record-source"
DIAGNOSIS_CODE_SYSTEM = "urn:hellopuppy:kr-mafra-veterinary-diagnosis"
REGISTRATION_SYSTEM = "urn:hellopuppy:kr-animal-registration"


def _full_url(pet_id: Any, kind: str, item_id: Any) -> str:
    return f"urn:uuid:{uuid.uuid5(_FHIR_NAMESPACE, f'{pet_id}/{kind}/{item_id}')}"


def _note(*parts: str) -> list[dict[str, str]]:
    text = "\n".join(part for part in parts if part)
    return [{"text": text}] if text else []


def _source_meta(record: dict[str, Any]) -> dict[str, Any]:
    source = record.get("source") or "guardian"
    display = "동물병원 입력" if source == "clinic" else "보호자 입력"
    return {"tag": [{"system": SOURCE_SYSTEM, "code": source, "display": display}]}


def _author_note(record: dict[str, Any]) -> str:
    if record.get("source") != "clinic":
        return ""
    license_text = f" (면허 {record['author_license']})" if record.get("author_license") else ""
    return f"입력: {record.get('clinic') or '동물병원'} {record.get('author_name', '')}{license_text}".strip()


def _narrative(rows: list[tuple[str, str]]) -> dict[str, str]:
    body = "".join(f"<p><b>{escape(label)}</b>: {escape(value)}</p>" for label, value in rows if value)
    return {"status": "generated", "div": f'<div xmlns="http://www.w3.org/1999/xhtml">{body or "<p>기록</p>"}</div>'}


def _record_resources(record: dict[str, Any], patient_ref: dict[str, str], pet_id: Any) -> list[tuple[str, dict[str, Any]]]:
    details = record.get("details") or {}
    record_type = record["record_type"]
    when = record["record_date"]
    clinic = record.get("clinic") or ""
    notes = record.get("notes") or ""
    author = _author_note(record)
    base = {"meta": _source_meta(record)}
    url = _full_url(pet_id, f"record-{record_type}", record["id"])

    if record_type == "visit":
        rows = [
            ("방문 사유", details.get("reason", "")), ("S 보호자 진술", details.get("subjective", "")),
            ("O 검사·관찰 소견", details.get("findings", "")), ("A 진단", details.get("diagnosis", "")),
            ("P 처치", details.get("treatment", "")), ("P 처방", details.get("prescription", "")),
            ("검사", details.get("tests", "")), ("다음 내원일", details.get("next_visit_date", "")), ("메모", notes),
        ]
        encounter = {
            "resourceType": "Encounter", **base, "status": "finished",
            "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "AMB", "display": "ambulatory"},
            "subject": patient_ref, "period": {"start": when}, "text": _narrative(rows),
        }
        if details.get("reason"):
            encounter["reasonCode"] = [{"text": details["reason"]}]
        if clinic:
            encounter["serviceProvider"] = {"display": clinic}
        vet_name = details.get("vet_name") or record.get("author_name")
        if vet_name:
            encounter["participant"] = [{"individual": {"display": vet_name}}]
        resources = [(url, encounter)]
        if details.get("diagnosis"):
            condition = {
                "resourceType": "Condition", **base,
                "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-category", "code": "encounter-diagnosis"}]}],
                "code": _diagnosis_code(details["diagnosis"], details.get("diagnosis_code")),
                "subject": patient_ref, "encounter": {"reference": url}, "recordedDate": when,
            }
            resources.append((_full_url(pet_id, "visit-diagnosis", record["id"]), condition))
        return resources

    if record_type == "vaccination":
        label = VACCINE_LABELS.get(details.get("vaccine_type", ""), "백신")
        resource = {
            "resourceType": "Immunization", **base, "status": "completed",
            "vaccineCode": {"text": " · ".join(part for part in (label, details.get("product", "")) if part)},
            "patient": patient_ref, "occurrenceDateTime": when,
            "note": _note(f"다음 접종 예정일: {details['next_due_date']}" if details.get("next_due_date") else "", notes, author),
        }
        if details.get("dose_number"):
            resource["protocolApplied"] = [{"doseNumberString": details["dose_number"]}]
        if clinic or details.get("vet_name"):
            resource["performer"] = [{"actor": {"display": " ".join(part for part in (clinic, details.get("vet_name", "")) if part)}}]
        return [(url, _drop_empty(resource))]

    if record_type in {"medication", "parasite"}:
        if record_type == "parasite":
            name = " · ".join(part for part in (PARASITE_LABELS.get(details.get("parasite_type", ""), "기생충 예방"), details.get("product", "")) if part)
            status = "completed"
            dosage_text = ""
            extra = f"다음 투여 예정일: {details['next_due_date']}" if details.get("next_due_date") else ""
            category = {"text": "기생충 예방"}
        else:
            name = details["drug_name"]
            status = "stopped" if details.get("medication_status") == "stopped" else "active"
            dosage_text = " ".join(part for part in (details.get("dose", ""), details.get("frequency", "")) if part)
            extra = ""
            category = {"text": "복용 약"}
        period = {key: value for key, value in (("start", details.get("start_date") or when), ("end", details.get("end_date", ""))) if value}
        dosage: dict[str, Any] = {}
        if dosage_text:
            dosage["text"] = dosage_text
        if details.get("route"):
            dosage["route"] = {"text": ROUTE_LABELS.get(details["route"], details["route"])}
        resource = {
            "resourceType": "MedicationStatement", **base, "status": status, "category": category,
            "medicationCodeableConcept": {"text": name}, "subject": patient_ref, "effectivePeriod": period,
            "dosage": [dosage] if dosage else [],
            "reasonCode": [{"text": details["purpose"]}] if details.get("purpose") else [],
            "informationSource": {"display": clinic} if clinic else None,
            "note": _note(extra, notes, author),
        }
        return [(url, _drop_empty(resource))]

    if record_type == "condition":
        status = details.get("condition_status") or "active"
        resource = {
            "resourceType": "Condition", **base,
            "clinicalStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical", "code": "resolved" if status == "resolved" else "active"}]},
            "verificationStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-ver-status", "code": "provisional" if status == "suspected" else "confirmed"}]},
            "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-category", "code": "problem-list-item"}]}],
            "code": _diagnosis_code(details["condition_name"], details.get("diagnosis_code")),
            "subject": patient_ref, "onsetDateTime": details.get("diagnosed_date") or when, "recordedDate": when,
            "note": _note(clinic, notes, author),
        }
        return [(url, _drop_empty(resource))]

    if record_type == "allergy":
        severity = details.get("severity", "")
        resource = {
            "resourceType": "AllergyIntolerance", **base,
            "clinicalStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical", "code": "active"}]},
            "category": [ALLERGY_CATEGORIES[details["allergy_category"]]] if details.get("allergy_category") in ALLERGY_CATEGORIES else [],
            "criticality": "high" if severity == "severe" else ("low" if severity else None),
            "code": {"text": details["substance"]}, "patient": patient_ref, "recordedDate": when,
            "reaction": [{"manifestation": [{"text": details.get("reaction") or "반응 기록 없음"}], **({"severity": severity} if severity else {})}],
            "note": _note(notes, author),
        }
        return [(url, _drop_empty(resource))]

    if record_type == "surgery":
        anesthesia = {"general": "전신마취", "sedation": "진정", "local": "국소마취", "none": "마취 없음"}.get(details.get("anesthesia", ""), "")
        resource = {
            "resourceType": "Procedure", **base, "status": "completed", "code": {"text": details["procedure"]},
            "subject": patient_ref, "performedDateTime": when,
            "performer": [{"actor": {"display": clinic}}] if clinic else [],
            "complication": [{"text": details["anesthesia_reaction"]}] if details.get("anesthesia_reaction") else [],
            "note": _note(f"마취: {anesthesia}" if anesthesia else "", notes, author),
        }
        return [(url, _drop_empty(resource))]

    if record_type == "lab":
        conclusion = "\n".join(part for part in (details.get("result_summary", ""), f"이상 소견: {details['abnormal_findings']}" if details.get("abnormal_findings") else "") if part)
        resource = {
            "resourceType": "DiagnosticReport", **base, "status": "final", "code": {"text": details["test_name"]},
            "subject": patient_ref, "effectiveDateTime": when, "conclusion": conclusion,
            "performer": [{"display": clinic}] if clinic else [],
        }
        return [(url, _drop_empty(resource))]

    if record_type == "weight":
        resources = [(url, _weight_observation(details["weight_kg"], when, patient_ref, base))]
        if details.get("body_condition_score"):
            bcs = {
                "resourceType": "Observation", **base, "status": "final",
                "code": {"text": "체형점수(BCS, 9점 척도)"}, "subject": patient_ref,
                "effectiveDateTime": when, "valueInteger": details["body_condition_score"],
            }
            resources.append((_full_url(pet_id, "bcs", record["id"]), bcs))
        return resources

    text = details.get("symptom") or record.get("title") or "기타 기록"
    resource = {
        "resourceType": "Observation", **base, "status": "final",
        "code": {"text": "보호자 관찰 증상" if record_type == "symptom" else (record.get("title") or "기타 건강 기록")},
        "subject": patient_ref, "effectiveDateTime": when,
        "valueString": " · ".join(part for part in (text, details.get("duration", "")) if part),
        "note": _note(notes, author),
    }
    return [(url, _drop_empty(resource))]


def _diagnosis_code(text: str, code: str | None) -> dict[str, Any]:
    concept: dict[str, Any] = {"text": text}
    if code:
        concept["coding"] = [{"system": DIAGNOSIS_CODE_SYSTEM, "code": code, "display": text}]
    return concept


def _weight_observation(weight: float, when: str, patient_ref: dict[str, str], base: dict[str, Any]) -> dict[str, Any]:
    return {
        "resourceType": "Observation", **base, "status": "final",
        "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "vital-signs"}]}],
        "code": {"coding": [{"system": "http://loinc.org", "code": "29463-7", "display": "Body weight"}], "text": "체중"},
        "subject": patient_ref, "effectiveDateTime": when,
        "valueQuantity": {"value": weight, "unit": "kg", "system": "http://unitsofmeasure.org", "code": "kg"},
    }


def _drop_empty(resource: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in resource.items() if value not in (None, "", [], {})}


def to_fhir_bundle(summary: dict[str, Any], generated_at: str) -> dict[str, Any]:
    """Convert the guardian summary into an HL7 FHIR R4 collection Bundle."""
    pet = summary["pet"]
    pet_id = pet.get("id", "unknown")
    patient_url = _full_url(pet_id, "patient", pet_id)
    patient_ref = {"reference": patient_url}
    species = pet.get("species") or "dog"
    animal_extension = [{
        "url": "species",
        "valueCodeableConcept": {"coding": [SPECIES_CODING[species]], "text": SPECIES_LABELS[species]} if species in SPECIES_CODING else {"text": SPECIES_LABELS.get(species, species)},
    }]
    if pet.get("breed"):
        animal_extension.append({"url": "breed", "valueCodeableConcept": {"text": pet["breed"]}})
    gender_status = {"yes": "neutered", "no": "intact"}.get(pet.get("neutered", ""), "unknown")
    animal_extension.append({"url": "genderStatus", "valueCodeableConcept": {"coding": [{"system": "http://hl7.org/fhir/animal-genderstatus", "code": gender_status}]}})
    patient: dict[str, Any] = {
        "resourceType": "Patient",
        "extension": [{"url": "http://hl7.org/fhir/StructureDefinition/patient-animal", "extension": animal_extension}],
        "name": [{"text": pet.get("name") or "이름 미입력"}],
        "gender": {"male": "male", "female": "female"}.get(pet.get("sex", ""), "unknown"),
    }
    if pet.get("microchip_id"):
        patient["identifier"] = [{"system": REGISTRATION_SYSTEM, "value": pet["microchip_id"]}]
    if pet.get("birth_date"):
        patient["birthDate"] = pet["birth_date"]
    if pet.get("guardian_name") or pet.get("guardian_phone"):
        contact: dict[str, Any] = {"relationship": [{"text": "보호자"}]}
        if pet.get("guardian_name"):
            contact["name"] = {"text": pet["guardian_name"]}
        if pet.get("guardian_phone"):
            contact["telecom"] = [{"system": "phone", "value": pet["guardian_phone"]}]
        patient["contact"] = [contact]
    profile_rows = [
        ("털색·외형 특징", pet.get("coat_features", "")), ("혈액형", pet.get("blood_type", "")),
        ("생활환경", {"indoor": "실내", "outdoor": "실외", "both": "실내·실외"}.get(pet.get("living_environment", ""), "")),
        ("함께 사는 동물", pet.get("other_pets", "")), ("진료 시 주의사항", pet.get("allergies", "")),
        ("기타 병력 메모", pet.get("medical_notes", "")),
        ("생년월일", f"{pet['birth_date']} (추정)" if pet.get("birth_date") and pet.get("birth_date_estimated") else ""),
    ]
    patient["text"] = _narrative(profile_rows)

    entries = [{"fullUrl": patient_url, "resource": patient}]
    has_weight_record = any(record["record_type"] == "weight" for record in summary["records"])
    if pet.get("weight_kg") and not has_weight_record:
        observation = _weight_observation(pet["weight_kg"], (pet.get("updated_at") or generated_at)[:10], patient_ref, {"meta": _source_meta({})})
        entries.append({"fullUrl": _full_url(pet_id, "profile-weight", pet_id), "resource": observation})
    for record in summary["records"]:
        for url, resource in _record_resources(record, patient_ref, pet_id):
            entries.append({"fullUrl": url, "resource": resource})

    food = summary.get("food") or {}
    diet_rows = [
        ("사료", food.get("food_name", "")), ("하루 급여 횟수", str(food.get("meals_per_day") or "")),
        ("1회 급여량", food.get("amount_per_meal", "")), ("급여 시간", food.get("feeding_schedule", "")),
        ("간식·사람 음식", food.get("treats", "")), ("영양제", food.get("supplements", "")),
        ("최근 사료 변경일", food.get("diet_changed_date", "")), ("메모", food.get("food_notes", "")),
    ]
    if any(value for _, value in diet_rows):
        diet = {
            "resourceType": "Observation", "meta": _source_meta({}), "status": "final",
            "code": {"text": "식이 이력(Diet history)"}, "subject": patient_ref,
            "effectiveDateTime": (food.get("updated_at") or generated_at)[:10],
            "component": [{"code": {"text": label}, "valueString": value} for label, value in diet_rows if value],
        }
        entries.append({"fullUrl": _full_url(pet_id, "diet", pet_id), "resource": diet})

    for questionnaire in summary.get("questionnaires", []):
        entries.append({"fullUrl": _full_url(pet_id, "questionnaire", questionnaire["id"]), "resource": _questionnaire_response(questionnaire, patient_ref)})

    return {
        "resourceType": "Bundle",
        "meta": {"tag": [{"system": SOURCE_SYSTEM, "code": "guardian-held-record", "display": "보호자 보관 건강기록 - 동물병원 진료부 원본이 아님"}]},
        "identifier": {"system": "urn:hellopuppy:export", "value": str(uuid.uuid4())},
        "type": "collection",
        "timestamp": generated_at,
        "entry": entries,
    }


SYSTEM_LABELS = {
    "energy": "활력·기분", "appetite": "식욕", "water": "음수량", "urination": "소변", "stool": "대변",
    "vomiting": "구토", "respiratory": "기침·재채기·콧물", "breathing": "호흡", "skin": "피부·가려움",
    "eyes_ears": "눈·귀", "mobility": "걸음걸이·절뚝거림", "weight_change": "체중 변화", "behavior": "행동 변화·통증",
}
SYSTEM_VALUE_LABELS = {"normal": "평소와 같음", "increased": "늘었음", "decreased": "줄었음", "abnormal": "이상 있음", "unknown": "잘 모름"}
PROGRESSION_LABELS = {"better": "좋아지는 중", "same": "비슷함", "worse": "나빠지는 중", "fluctuating": "좋아졌다 나빠졌다 함"}


def _questionnaire_response(item: dict[str, Any], patient_ref: dict[str, str]) -> dict[str, Any]:
    answers = [
        ("clinic", "방문 예정 병원", item.get("clinic", "")),
        ("chief_complaint", "주 증상(방문 사유)", item.get("chief_complaint", "")),
        ("onset_date", "증상 시작일", item.get("onset_date", "")),
        ("frequency", "빈도·지속 시간", item.get("frequency", "")),
        ("progression", "경과", PROGRESSION_LABELS.get(item.get("progression", ""), "")),
        ("home_care", "집에서 한 조치·먹인 약", item.get("home_care", "")),
        ("recent_changes", "최근 변화(사료·환경·여행·접촉)", item.get("recent_changes", "")),
        ("concerns", "보호자 질문·걱정", item.get("concerns", "")),
    ]
    answers += [
        (f"system-{key}", SYSTEM_LABELS[key], SYSTEM_VALUE_LABELS.get(value, value))
        for key, value in (item.get("systems") or {}).items()
    ]
    resource = {
        "resourceType": "QuestionnaireResponse", "meta": _source_meta({}), "status": "completed",
        "subject": patient_ref, "authored": item.get("visit_date"),
        "item": [{"linkId": link, "text": text, "answer": [{"valueString": value}]} for link, text, value in answers if value],
    }
    return resource
