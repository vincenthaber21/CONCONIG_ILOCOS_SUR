(function () {
  function isCashierRoleSelected() {
    var sel = document.getElementById('id_member_role');
    if (!sel || sel.selectedIndex < 0) return false;
    var opt = sel.options[sel.selectedIndex];
    var label = ((opt && (opt.textContent || opt.label || opt.text)) || '').trim().toLowerCase();
    return label === 'cashier' || label.indexOf('cashier') !== -1;
  }

  function syncProjectCategoryFieldset() {
    var modules = document.querySelectorAll('.project-category-cashier-only');
    if (!modules.length) return;
    var show = isCashierRoleSelected();
    modules.forEach(function (el) {
      el.style.display = show ? '' : 'none';
    });
  }

  function bind() {
    syncProjectCategoryFieldset();
    var sel = document.getElementById('id_member_role');
    if (sel && !sel.dataset.pcRoleBound) {
      sel.dataset.pcRoleBound = '1';
      sel.addEventListener('change', syncProjectCategoryFieldset);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bind);
  } else {
    bind();
  }
})();
