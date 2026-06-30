const findBtn = document.getElementById("find-btn");
const resultDiv = document.getElementById("result");
const countrySelect = document.getElementById("country-select");

const map = L.map("map").setView([20, 0], 2);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 18,
  attribution: "&copy; OpenStreetMap contributors",
}).addTo(map);
let mapMarkers = [];

function clearMarkers() {
  mapMarkers.forEach((marker) => map.removeLayer(marker));
  mapMarkers = [];
}

function addMarker(lat, lon, name, book) {
  const marker = L.marker([lat, lon]).addTo(map);
  marker.bindPopup(`${escapeHtml(name)} — ${escapeHtml(book)}`);
  mapMarkers.push(marker);
}

function updateMapView() {
  if (mapMarkers.length === 2) {
    map.fitBounds(L.featureGroup(mapMarkers).getBounds(), { padding: [40, 40] });
  } else if (mapMarkers.length === 1) {
    map.setView(mapMarkers[0].getLatLng(), 6);
  }
}

function capitalize(text) {
  return text.replace(/\b\w/g, (c) => c.toUpperCase());
}

async function loadCountries() {
  try {
    const response = await fetch("/api/countries");
    if (!response.ok) return;
    const data = await response.json();
    for (const country of data.countries) {
      const option = document.createElement("option");
      option.value = country;
      option.textContent = capitalize(country);
      countrySelect.appendChild(option);
    }
  } catch (err) {
    // Leave the dropdown at "Any country" if this fails.
  }
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function renderEncounter(encounter) {
  const side = (name, book, location, time, evidence, lat, lon) => {
    const pinNote = lat == null || lon == null
      ? `<p class="no-pin-note">No pin available for ${escapeHtml(name)}.</p>`
      : "";
    return `
    <div class="character">
      <h2>${escapeHtml(name)}</h2>
      <p class="book">${escapeHtml(book)}</p>
      <p class="location">${escapeHtml(location)}</p>
      <p class="time">${escapeHtml(time)}</p>
      <blockquote>${escapeHtml(evidence)}</blockquote>
      ${pinNote}
    </div>
  `;
  };

  const supportNote = encounter.support_count > 1
    ? `<p class="support-count">Supported by ${encounter.support_count} pieces of evidence.</p>`
    : "";

  resultDiv.innerHTML = `
    <div class="encounter">
      ${side(encounter.character_a, encounter.book_a, encounter.location_a, encounter.time_a, encounter.evidence_a, encounter.lat_a, encounter.lon_a)}
      <div class="vs">&times;</div>
      ${side(encounter.character_b, encounter.book_b, encounter.location_b, encounter.time_b, encounter.evidence_b, encounter.lat_b, encounter.lon_b)}
    </div>
    ${supportNote}
  `;

  clearMarkers();
  if (encounter.lat_a != null && encounter.lon_a != null) {
    addMarker(encounter.lat_a, encounter.lon_a, encounter.character_a, encounter.book_a);
  }
  if (encounter.lat_b != null && encounter.lon_b != null) {
    addMarker(encounter.lat_b, encounter.lon_b, encounter.character_b, encounter.book_b);
  }
  updateMapView();
}

async function findEncounter() {
  const time = document.getElementById("time-select").value;
  const location = document.getElementById("location-select").value;
  const country = countrySelect.value;

  resultDiv.innerHTML = "<p class=\"status\">Searching…</p>";

  try {
    const countryParam = country ? `&country=${encodeURIComponent(country)}` : "";
    const response = await fetch(`/api/encounter?time=${time}&location=${location}${countryParam}`);
    if (!response.ok) {
      resultDiv.innerHTML = "<p class=\"status error\">Something went wrong. Please try again.</p>";
      return;
    }
    const data = await response.json();
    if (!data.found) {
      resultDiv.innerHTML = "<p class=\"status\">No encounters found for this combination. Try a broader filter.</p>";
      clearMarkers();
      return;
    }
    renderEncounter(data.encounter);
  } catch (err) {
    resultDiv.innerHTML = "<p class=\"status error\">Something went wrong. Please try again.</p>";
  }
}

findBtn.addEventListener("click", findEncounter);
loadCountries();
