// Apply the remembered theme before the first paint, like the portfolio (key "na-theme"); without a
// choice the system setting applies through CSS. A classic script, so it runs before the stylesheet.
(function () {
  "use strict";
  try {
    var theme = window.localStorage.getItem("na-theme");
    if (theme === "light" || theme === "dark") document.documentElement.dataset.theme = theme;
  } catch (e) {
    /* Storage can be disabled; the system theme still applies. */
  }
})();
