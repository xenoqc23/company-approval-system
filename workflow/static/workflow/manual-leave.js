document.addEventListener('DOMContentLoaded', () => {
  const form = document.querySelector('[data-manual-leave-form]');
  if (!form) return;
  const kind = form.querySelector('[name=leave_type]');
  const day = form.querySelector('[name=used_date]');
  const amounts = {annual: '1', am: '0.5', pm: '0.5', outing: '0.25'};
  const update = () => {
    const annual = kind.value === 'annual';
    form.querySelectorAll('[data-manual-time]').forEach(field => {
      field.hidden = annual;
      field.querySelector('input').required = !annual;
    });
    form.querySelector('[data-manual-preview]').textContent =
      `${day.value || '선택한 사용일'} · ${amounts[kind.value]}일을 사용연차에 추가하고 잔여연차에서 차감합니다.`;
  };
  kind.addEventListener('change', update);
  day.addEventListener('change', update);
  update();
});
