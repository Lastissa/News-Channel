(function () {
  "use strict";

  /* Chrome can keep an old csrftoken cookie around after a domain/cookie
     change. On a CSRF 419 the server sends a fresh token in X-CSRF-Token;
     resend the same request once with it so the tab heals itself. */
  var MESSAGE = "Your session expired or the page is stale. Refresh the page and try again.";
  var nativeFetch = window.fetch;
  if (typeof nativeFetch !== "function") return;

  function token() {
    var match = document.cookie.match(/(?:^|; )csrftoken=([^;]*)/);
    if (match) {
      try { return decodeURIComponent(match[1]); } catch (e) { return match[1]; }
    }
    var input = document.querySelector('input[name="csrfmiddlewaretoken"]');
    return input ? input.value : "";
  }

  function headersWith(from, value) {
    var h = new Headers(from || {});
    h.set("X-CSRFToken", value || token());
    h.set("X-Requested-With", "XMLHttpRequest");
    return h;
  }

  window.fetch = function (input, init) {
    var url = input;
    var options = init || {};
    if (input && typeof input === "object" && typeof input.url === "string") {
      url = input.url;
      options = {
        method: input.method,
        headers: headersWith(input.headers, token()),
        body: input.body,
        credentials: input.credentials || "same-origin",
        cache: input.cache,
        mode: input.mode,
        redirect: input.redirect,
        referrer: input.referrer,
        integrity: input.integrity,
        keepalive: input.keepalive,
        signal: input.signal
      };
    } else {
      options.headers = headersWith(options.headers, token());
      if (!options.credentials) options.credentials = "same-origin";
    }

    var body = options.body;
    var reusable = body == null || typeof body === "string" ||
      (typeof FormData !== "undefined" && body instanceof FormData) ||
      (typeof URLSearchParams !== "undefined" && body instanceof URLSearchParams);
    var retry = options.headers.get("X-CSRF-Retry") === "1";

    return nativeFetch.call(window, url, options).then(function (response) {
      var fresh = response.headers.get("X-CSRF-Token");
      if (retry || response.status !== 419 || !fresh || !reusable) return response;
      return response.clone().json().catch(function () { return null; }).then(function (data) {
        if (!data || data.detail !== MESSAGE) return response;
        options.headers = headersWith(options.headers, fresh);
        options.headers.set("X-CSRF-Retry", "1");
        return nativeFetch.call(window, url, options);
      });
    });
  };
})();