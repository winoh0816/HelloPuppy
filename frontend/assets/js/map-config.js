/* Leaflet + OpenStreetMap are used for a no-API-key community map. */
window.loadHelloPuppyMapLibrary = function () {
    if (window.L?.map) return Promise.resolve(window.L);
    if (window.helloPuppyMapLibraryPromise) return window.helloPuppyMapLibraryPromise;
    window.helloPuppyMapLibraryPromise = new Promise((resolve, reject) => {
        const stylesheet = document.createElement("link");
        stylesheet.rel = "stylesheet";
        stylesheet.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
        document.head.append(stylesheet);

        const script = document.createElement("script");
        script.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
        script.async = true;
        script.onload = () => window.L?.map
            ? resolve(window.L)
            : reject(new Error("지도 라이브러리를 초기화하지 못했습니다."));
        script.onerror = () => reject(new Error("Leaflet 지도 라이브러리를 불러오지 못했습니다."));
        document.head.append(script);
    });
    return window.helloPuppyMapLibraryPromise;
};
