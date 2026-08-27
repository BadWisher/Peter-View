(function () {
  var orig = Element.prototype.scrollIntoView;
  Element.prototype.scrollIntoView = function () {
    if (this.closest && this.closest(".md-sidebar--primary")) return;
    return orig.apply(this, arguments);
  };

  function pinNav() {
    var wrap = document.querySelector(".md-sidebar--primary .md-sidebar__scrollwrap");
    if (wrap) wrap.scrollTop = 0;
  }

  pinNav();
  if (typeof document$ !== "undefined" && document$.subscribe) {
    document$.subscribe(pinNav);
  }
  window.addEventListener("load", function () {
    pinNav();
    window.setTimeout(pinNav, 0);
    window.setTimeout(pinNav, 200);
  });
})();
