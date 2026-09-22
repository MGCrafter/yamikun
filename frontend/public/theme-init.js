(function () {
  try {
    var theme = localStorage.getItem("yami-theme") || "dark";
    document.documentElement.setAttribute("data-theme", theme);
    document.documentElement.classList.toggle("dark", theme === "dark");
  } catch (e) {
    // Keep the static dark default if localStorage is unavailable.
  }
})();
