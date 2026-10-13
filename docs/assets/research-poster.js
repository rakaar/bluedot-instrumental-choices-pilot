const appendices = [...document.querySelectorAll('.appendix')];
const appendixButton = document.querySelector('#toggle-appendices');

function updateAppendixButton() {
  const allOpen = appendices.every(appendix => appendix.open);
  appendixButton.textContent = allOpen ? 'Collapse all appendices' : 'Expand all appendices';
  appendixButton.setAttribute('aria-expanded', String(allOpen));
}

appendixButton.addEventListener('click', () => {
  const open = !appendices.every(appendix => appendix.open);
  appendices.forEach(appendix => { appendix.open = open; });
  updateAppendixButton();
});
appendices.forEach(appendix => appendix.addEventListener('toggle', updateAppendixButton));

function revealHashTarget() {
  const target = document.getElementById(location.hash.slice(1));
  if (!target) return;
  const appendix = target.closest('.appendix');
  if (appendix) {
    appendix.open = true;
    target.scrollIntoView({ behavior: 'instant', block: 'start' });
  }
}
window.addEventListener('hashchange', revealHashTarget);
revealHashTarget();
document.querySelector('#print-poster').addEventListener('click', () => window.print());
