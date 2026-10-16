/* Reuse the permission-filtered desktop menu in a native, focus-trapped dialog. */
document.addEventListener('DOMContentLoaded', () => {
  const sidebar = document.querySelector('#workspace-navigation');
  const menu = document.querySelector('#mobile-navigation');
  const toggle = document.querySelector('[data-mobile-menu-open]');
  if (!sidebar || !menu || !toggle || typeof menu.showModal !== 'function') return;

  const anchor = document.createComment('workspace navigation');
  sidebar.before(anchor);
  const mobile = window.matchMedia('(max-width: 1079px)');
  document.documentElement.classList.add('mobile-navigation-ready');

  const restore = () => {
    anchor.after(sidebar);
    toggle.setAttribute('aria-expanded', 'false');
    document.body.classList.remove('mobile-navigation-open');
  };
  toggle.addEventListener('click', () => {
    if (!mobile.matches || menu.open) return;
    menu.append(sidebar);
    menu.showModal();
    toggle.setAttribute('aria-expanded', 'true');
    document.body.classList.add('mobile-navigation-open');
  });
  menu.querySelector('[data-mobile-menu-close]').addEventListener('click', () => menu.close());
  menu.addEventListener('close', restore);
  menu.addEventListener('click', event => {
    if (event.target !== menu) return;
    const box = menu.getBoundingClientRect();
    if (event.clientX < box.left || event.clientX > box.right ||
        event.clientY < box.top || event.clientY > box.bottom) menu.close();
  });
  mobile.addEventListener('change', () => {
    if (!mobile.matches && menu.open) menu.close();
  });
  // Do not restore a modal over the destination when returning via browser Back.
  window.addEventListener('pageshow', () => {
    if (menu.open) menu.close();
    restore();
  });
});
