// Apply the saved palette before the stylesheet paints, even if storage is blocked.
(() => {
    let saved;
    try { saved = localStorage.getItem('frc_theme'); } catch { /* Use the default palette. */ }
    document.documentElement.dataset.theme = ['default','light','citrus','poofs','orbit','hightide'].includes(saved) ? saved : 'default';
})();
