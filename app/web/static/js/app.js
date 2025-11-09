const navLinks = document.querySelectorAll(".primary-nav .nav-link");
navLinks.forEach((link) => {
  if (link.getAttribute("href") === window.location.pathname) {
    link.classList.add("active");
  }
});

async function refreshStreamStatus() {
  const container = document.querySelector("[data-stream-status]");
  if (!container) {
    return;
  }

  try {
    const response = await fetch("/api/v1/stream/status");
    if (!response.ok) return;
    const payload = await response.json();
    const statusField = container.querySelector('[data-field="status"]');
    const bitrateField = container.querySelector('[data-field="bitrate"]');
    const uptimeField = container.querySelector('[data-field="uptime"]');
    if (statusField) {
      statusField.textContent = payload.status.replace(/\b\w/g, (c) => c.toUpperCase());
      statusField.className = `value status-${payload.status}`;
    }
    if (bitrateField && payload.metrics) {
      bitrateField.textContent = `${payload.metrics.bitrate_kbps} kbps`;
    }
    if (uptimeField) {
      const hours = (payload.uptime_seconds / 3600).toFixed(2);
      uptimeField.textContent = hours;
    }
  } catch (error) {
    console.error("Failed to refresh stream status", error);
  }
}

refreshStreamStatus();
setInterval(refreshStreamStatus, 30000);
