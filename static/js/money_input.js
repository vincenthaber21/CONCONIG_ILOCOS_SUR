/**
 * Live thousand-separator formatting for .js-money-input fields.
 * Displays 50,000.00 while typing; submits plain decimals to Django.
 */
(function (window, document) {
  "use strict";

  var SELECTOR = "input.js-money-input";

  function decimalPlaces(el) {
    var n = parseInt(el.getAttribute("data-decimal-places") || "2", 10);
    return Number.isFinite(n) && n >= 0 ? n : 2;
  }

  function strip(raw) {
    return String(raw == null ? "" : raw)
      .replace(/₱/g, "")
      .replace(/Php/gi, "")
      .replace(/,/g, "")
      .replace(/\s/g, "")
      .trim();
  }

  function parseNumber(raw) {
    var cleaned = strip(raw);
    if (!cleaned || cleaned === "." || cleaned === "-") return NaN;
    var n = Number(cleaned);
    return Number.isFinite(n) ? n : NaN;
  }

  function formatGrouped(intPart) {
    var neg = intPart.charAt(0) === "-";
    var digits = neg ? intPart.slice(1) : intPart;
    digits = digits.replace(/\D/g, "") || "0";
    var withCommas = digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    return neg ? "-" + withCommas : withCommas;
  }

  /** Format while typing: keep trailing decimal point / partial cents. */
  function formatLive(raw, places) {
    var cleaned = strip(raw);
    if (!cleaned) return "";

    var neg = cleaned.charAt(0) === "-";
    if (neg) cleaned = cleaned.slice(1);

    cleaned = cleaned.replace(/[^\d.]/g, "");
    var firstDot = cleaned.indexOf(".");
    var intPart;
    var fracPart = null;
    var hasDot = firstDot !== -1;

    if (hasDot) {
      intPart = cleaned.slice(0, firstDot) || "0";
      fracPart = cleaned.slice(firstDot + 1).replace(/\./g, "").slice(0, places);
    } else {
      intPart = cleaned || "0";
    }

    intPart = intPart.replace(/^0+(?=\d)/, "");
    if (!intPart) intPart = "0";

    var out = formatGrouped(intPart);
    if (neg && out !== "0") out = "-" + out;
    if (hasDot) out += "." + (fracPart == null ? "" : fracPart);
    return out;
  }

  function formatBlur(raw, places) {
    var n = parseNumber(raw);
    if (!Number.isFinite(n)) return strip(raw) ? String(raw) : "";
    return n.toLocaleString("en-PH", {
      minimumFractionDigits: places,
      maximumFractionDigits: places,
    });
  }

  function caretFromDigits(formatted, digitIndex) {
    if (digitIndex <= 0) return 0;
    var seen = 0;
    for (var i = 0; i < formatted.length; i++) {
      if (/\d/.test(formatted.charAt(i))) {
        seen += 1;
        if (seen >= digitIndex) return i + 1;
      }
    }
    return formatted.length;
  }

  function digitIndexBeforeCaret(value, caret) {
    var count = 0;
    var end = Math.min(caret || 0, value.length);
    for (var i = 0; i < end; i++) {
      if (/\d/.test(value.charAt(i))) count += 1;
    }
    return count;
  }

  function onInput(e) {
    var el = e.target;
    if (!el || !el.classList || !el.classList.contains("js-money-input")) return;
    if (el.readOnly || el.disabled) return;

    var places = decimalPlaces(el);
    var start = el.selectionStart;
    var digitsBefore = digitIndexBeforeCaret(el.value, start);
    var next = formatLive(el.value, places);
    if (next === el.value) return;
    el.value = next;
    var pos = caretFromDigits(next, digitsBefore);
    try {
      el.setSelectionRange(pos, pos);
    } catch (err) {}
  }

  function onBlur(e) {
    var el = e.target;
    if (!el || !el.classList || !el.classList.contains("js-money-input")) return;
    if (el.readOnly || el.disabled) return;
    if (!strip(el.value)) {
      el.value = "";
      return;
    }
    el.value = formatBlur(el.value, decimalPlaces(el));
  }

  function prepareForm(form) {
    if (!form || form.dataset.moneyInputBound === "1") return;
    form.dataset.moneyInputBound = "1";
    form.addEventListener(
      "submit",
      function () {
        stripForm(form);
      },
      true
    );
  }

  function stripForm(form) {
    if (!form) return;
    form.querySelectorAll(SELECTOR).forEach(function (el) {
      var cleaned = strip(el.value);
      if (cleaned !== el.value) el.value = cleaned;
    });
  }

  function bindInput(el) {
    if (!el || el.dataset.moneyInputBound === "1") return;
    el.dataset.moneyInputBound = "1";
    // Initial display format for server-rendered values
    if (strip(el.value) && !el.value.includes(",")) {
      el.value = formatBlur(el.value, decimalPlaces(el));
    }
    el.addEventListener("input", onInput);
    el.addEventListener("blur", onBlur);
    if (el.form) prepareForm(el.form);
  }

  function scan(root) {
    (root || document).querySelectorAll(SELECTOR).forEach(bindInput);
  }

  function ready(fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn);
    } else {
      fn();
    }
  }

  ready(function () {
    scan(document);
  });

  window.MoneyInput = {
    scan: scan,
    bind: bindInput,
    parse: parseNumber,
    strip: strip,
    stripForm: stripForm,
    format: formatBlur,
    formatLive: formatLive,
  };
})(window, document);
