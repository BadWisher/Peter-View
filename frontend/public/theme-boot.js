(() => {
  try {
    const theme = localStorage.getItem("pv-theme");
    if (theme === "dark") {
      document.documentElement.dataset.theme = theme;
    }
  } catch {
    /* private mode */
  }
})();
