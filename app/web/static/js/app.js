const navLinks = document.querySelectorAll(".primary-nav .nav-link");
navLinks.forEach((link) => {
  if (link.getAttribute("href") === window.location.pathname) {
    link.classList.add("active");
  }
});

const notice = document.createElement("div");
notice.className = "dev-notice";
notice.innerHTML =
  "<strong>Heads up:</strong> These pages are static previews. Wire them to API endpoints before production.";
document.body.appendChild(notice);

setTimeout(() => {
  notice.classList.add("visible");
}, 150);
