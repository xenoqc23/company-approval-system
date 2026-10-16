/* Refresh only the login token; never replay a rejected POST or relax CSRF. */
document.addEventListener('DOMContentLoaded', () => {
  const form = document.querySelector('[data-login-form]');
  if (!form) return;
  const field = form.querySelector('[name=csrfmiddlewaretoken]');
  const button = form.querySelector('button[type=submit]');
  const label = button.querySelector('[data-login-label]');
  const error = form.querySelector('[data-login-error]');
  let busy = false;
  let allowSubmit = false;
  const reset = () => {
    busy = false;
    allowSubmit = false;
    button.disabled = false;
    form.removeAttribute('aria-busy');
    label.textContent = '로그인';
  };
  window.addEventListener('pageshow', () => {
    reset();
    error.hidden = true;
  });
  form.addEventListener('submit', async event => {
    if (allowSubmit) {
      allowSubmit = false;
      return;
    }
    event.preventDefault();
    if (busy) return;
    busy = true;
    button.disabled = true;
    form.setAttribute('aria-busy', 'true');
    label.textContent = '확인 중…';
    error.hidden = true;
    try {
      const response = await fetch(form.dataset.csrfUrl, {
        method: 'GET', mode: 'same-origin', credentials: 'same-origin',
        cache: 'no-store', headers: {'Accept': 'application/json'},
      });
      if (!response.ok || response.redirected) throw new Error('token refresh failed');
      const data = await response.json();
      if (typeof data.token !== 'string' || !/^[a-zA-Z0-9]{64}$/.test(data.token)) {
        throw new Error('invalid token response');
      }
      field.value = data.token;
      button.disabled = false;
      allowSubmit = true;
      form.requestSubmit(event.submitter || button);
      allowSubmit = false;
      // Native validation may stop submission if an input changed during fetch.
      if (!form.checkValidity()) reset();
    } catch {
      reset();
      error.textContent = '로그인 정보를 새로 불러오지 못했습니다. 연결을 확인하고 다시 눌러 주세요.';
      error.hidden = false;
    }
  });
});
