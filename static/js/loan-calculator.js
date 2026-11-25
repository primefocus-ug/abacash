(function () {
  const widget = document.getElementById('loan-calculator');
  if (!widget) return;

  const trigger = document.getElementById('loan-calculator-trigger');
  const panel = document.getElementById('loan-calculator-panel');
  const closeButton = document.getElementById('loan-calculator-close');
  const shareButton = document.getElementById('loan-calculator-share');
  const amountInput = document.getElementById('loan-calc-amount');
  const rateInput = document.getElementById('loan-calc-rate');
  const termInput = document.getElementById('loan-calc-term');
  const frequencyInput = document.getElementById('loan-calc-frequency');
  const methodInput = document.getElementById('loan-calc-method');
  const errorMessage = document.getElementById('loan-calc-error');
  const shareStatus = document.getElementById('loan-calc-share-status');
  const results = document.getElementById('loan-calc-results');
  const currency = widget.dataset.currency || 'UGX';
  let debounceTimer;
  let activeRequest;

  widget.querySelector('[data-calc-currency]').textContent = currency;

  function showError(message) {
    errorMessage.textContent = message;
    errorMessage.hidden = false;
  }

  function formatMoney(value) {
    const [whole, fraction = ''] = String(value).split('.');
    const groupedWhole = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    return `${currency} ${groupedWhole}.${fraction.padEnd(4, '0').slice(0, 4)}`;
  }

  function calculatorParams() {
    return new URLSearchParams({
      principal: amountInput.value,
      monthly_rate: rateInput.value,
      term_months: termInput.value,
      frequency: frequencyInput.value,
      method: methodInput.value,
    });
  }

  function showShareStatus(message, isError) {
    shareStatus.textContent = message;
    shareStatus.dataset.state = isError ? 'error' : 'success';
    shareStatus.hidden = false;
  }

  function downloadPdf(blob) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'loan-schedule-estimate.pdf';
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  async function shareSchedule() {
    const fields = [amountInput, rateInput, termInput];
    if (!fields.every(input => input.reportValidity())) return;

    shareButton.disabled = true;
    shareStatus.hidden = true;
    showShareStatus('Preparing your branded PDF…', false);
    try {
      const response = await fetch(`${widget.dataset.pdfUrl}?${calculatorParams()}`, {
        headers: { Accept: 'application/pdf, application/json' },
      });
      if (!response.ok) {
        const contentType = response.headers.get('content-type') || '';
        const errorBody = contentType.includes('application/json')
          ? await response.json()
          : null;
        throw new Error(errorBody?.error || 'Unable to create the loan schedule PDF.');
      }
      if (!response.headers.get('content-type')?.includes('application/pdf')) {
        throw new Error('Refresh the page to continue using the calculator.');
      }

      const blob = await response.blob();
      const file = typeof File === 'undefined'
        ? null
        : new File([blob], 'loan-schedule-estimate.pdf', { type: 'application/pdf' });
      if (
        file &&
        typeof navigator.share === 'function' &&
        (!navigator.canShare || navigator.canShare({ files: [file] }))
      ) {
        try {
          await navigator.share({
            files: [file],
            title: 'Loan repayment schedule',
            text: 'Branded loan repayment schedule estimate',
          });
          showShareStatus('Loan schedule shared.', false);
          return;
        } catch (error) {
          if (error.name === 'AbortError') {
            showShareStatus('Sharing canceled.', false);
            return;
          }
        }
      }

      downloadPdf(blob);
      showShareStatus('PDF downloaded. You can now share it from your device.', false);
    } catch (error) {
      showShareStatus(error.message || 'Unable to create the loan schedule PDF.', true);
    } finally {
      shareButton.disabled = false;
    }
  }

  function syncApplicationTerms() {
    const applicationForm = document.getElementById('loan-form');
    if (!applicationForm) return;

    const productInput = applicationForm.querySelector('[name="product"]');
    const product = productInput?.selectedOptions?.[0];
    if (!product || !product.value) return;

    const applicationField = name => applicationForm.querySelector(`[name="${name}"]`);
    const amount = applicationField('principal')?.value;
    const rate = product.dataset.rate;
    const term = applicationField('term_months')?.value;
    const frequency = applicationField('frequency')?.value;
    const method = applicationField('interest_method')?.value || product.dataset.method;

    if (amount) amountInput.value = amount;
    if (rate) rateInput.value = rate;
    if (term) termInput.value = term;
    if (frequencyInput.querySelector(`option[value="${frequency}"]`)) {
      frequencyInput.value = frequency;
    }
    if (methodInput.querySelector(`option[value="${method}"]`)) {
      methodInput.value = method;
    }
  }

  async function updateEstimate() {
    if (activeRequest) activeRequest.abort();

    const principal = Number(amountInput.value);
    const monthlyRate = Number(rateInput.value);
    const termMonths = Number(termInput.value);
    if (
      !Number.isFinite(principal) || principal <= 0 ||
      !Number.isFinite(monthlyRate) || monthlyRate < 0 ||
      !Number.isInteger(termMonths) || termMonths < 1 || termMonths > 60
    ) {
      results.hidden = true;
      showError('Enter an amount above zero, a valid rate, and a term from 1 to 60 months.');
      return;
    }

    errorMessage.hidden = true;
    const params = calculatorParams();
    const controller = new AbortController();
    activeRequest = controller;
    panel.setAttribute('aria-busy', 'true');

    try {
      const response = await fetch(`${widget.dataset.previewUrl}?${params}`, {
        headers: { Accept: 'application/json' },
        signal: controller.signal,
      });
      if (!response.headers.get('content-type')?.includes('application/json')) {
        throw new Error('Refresh the page to continue using the calculator.');
      }
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Unable to calculate this estimate.');
      if (activeRequest !== controller) return;

      document.getElementById('loan-calc-average').textContent = formatMoney(result.average_payment);
      document.getElementById('loan-calc-interest').textContent = formatMoney(result.total_interest);
      document.getElementById('loan-calc-total').textContent = formatMoney(result.total_repayable);
      document.getElementById('loan-calc-first').textContent = formatMoney(result.first_payment);
      document.getElementById('loan-calc-final').textContent = formatMoney(result.final_payment);
      document.getElementById('loan-calc-period-count').textContent = result.period_count;
      results.hidden = false;
    } catch (error) {
      if (error.name === 'AbortError') return;
      results.hidden = true;
      showError(error.message || 'Unable to calculate right now. Try again.');
    } finally {
      if (activeRequest === controller) {
        activeRequest = null;
        panel.removeAttribute('aria-busy');
      }
    }
  }

  function scheduleEstimate() {
    window.clearTimeout(debounceTimer);
    debounceTimer = window.setTimeout(updateEstimate, 220);
  }

  function setOpen(open) {
    panel.hidden = !open;
    trigger.setAttribute('aria-expanded', String(open));
    if (open) {
      syncApplicationTerms();
      updateEstimate();
      amountInput.focus();
    } else {
      window.clearTimeout(debounceTimer);
      if (activeRequest) activeRequest.abort();
      trigger.focus();
    }
  }

  trigger.addEventListener('click', () => setOpen(panel.hidden));
  closeButton.addEventListener('click', () => setOpen(false));
  shareButton.addEventListener('click', shareSchedule);
  [amountInput, rateInput, termInput, frequencyInput, methodInput]
    .forEach(input => input.addEventListener('input', scheduleEstimate));
  [frequencyInput, methodInput].forEach(input => input.addEventListener('change', scheduleEstimate));

  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !panel.hidden) setOpen(false);
  });
  document.addEventListener('click', event => {
    if (!panel.hidden && !widget.contains(event.target)) setOpen(false);
  });
})();
(function () {
  const widget = document.getElementById('loan-calculator');
  if (!widget) return;

  const trigger = document.getElementById('loan-calculator-trigger');
  const panel = document.getElementById('loan-calculator-panel');
  const closeButton = document.getElementById('loan-calculator-close');
  const shareButton = document.getElementById('loan-calculator-share');
  const amountInput = document.getElementById('loan-calc-amount');
  const rateInput = document.getElementById('loan-calc-rate');
  const termInput = document.getElementById('loan-calc-term');
  const frequencyInput = document.getElementById('loan-calc-frequency');
  const methodInput = document.getElementById('loan-calc-method');
  const errorMessage = document.getElementById('loan-calc-error');
  const shareStatus = document.getElementById('loan-calc-share-status');
  const results = document.getElementById('loan-calc-results');
  const currency = widget.dataset.currency || 'UGX';
  let debounceTimer;
  let activeRequest;

  widget.querySelector('[data-calc-currency]').textContent = currency;

  function showError(message) {
    errorMessage.textContent = message;
    errorMessage.hidden = false;
  }

  function formatMoney(value) {
    return `${currency} ${Number(value).toLocaleString(undefined, {
      minimumFractionDigits: 0,
      maximumFractionDigits: 2,
    })}`;
  }

  function calculatorParams() {
    return new URLSearchParams({
      principal: amountInput.value,
      monthly_rate: rateInput.value,
      term_months: termInput.value,
      frequency: frequencyInput.value,
      method: methodInput.value,
    });
  }

  function showShareStatus(message, isError) {
    shareStatus.textContent = message;
    shareStatus.dataset.state = isError ? 'error' : 'success';
    shareStatus.hidden = false;
  }

  function downloadPdf(blob) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'loan-schedule-estimate.pdf';
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  async function shareSchedule() {
    const fields = [amountInput, rateInput, termInput];
    if (!fields.every(input => input.reportValidity())) return;

    shareButton.disabled = true;
    shareStatus.hidden = true;
    showShareStatus('Preparing your branded PDF…', false);
    try {
      const response = await fetch(`${widget.dataset.pdfUrl}?${calculatorParams()}`, {
        headers: { Accept: 'application/pdf, application/json' },
      });
      if (!response.ok) {
        const contentType = response.headers.get('content-type') || '';
        const errorBody = contentType.includes('application/json')
          ? await response.json()
          : null;
        throw new Error(errorBody?.error || 'Unable to create the loan schedule PDF.');
      }
      if (!response.headers.get('content-type')?.includes('application/pdf')) {
        throw new Error('Refresh the page to continue using the calculator.');
      }

      const blob = await response.blob();
      const file = typeof File === 'undefined'
        ? null
        : new File([blob], 'loan-schedule-estimate.pdf', { type: 'application/pdf' });
      if (
        file &&
        typeof navigator.share === 'function' &&
        (!navigator.canShare || navigator.canShare({ files: [file] }))
      ) {
        try {
          await navigator.share({
            files: [file],
            title: 'Loan repayment schedule',
            text: 'Branded loan repayment schedule estimate',
          });
          showShareStatus('Loan schedule shared.', false);
          return;
        } catch (error) {
          if (error.name === 'AbortError') {
            showShareStatus('Sharing canceled.', false);
            return;
          }
        }
      }

      downloadPdf(blob);
      showShareStatus('PDF downloaded. You can now share it from your device.', false);
    } catch (error) {
      showShareStatus(error.message || 'Unable to create the loan schedule PDF.', true);
    } finally {
      shareButton.disabled = false;
    }
  }

  function syncApplicationTerms() {
    const applicationForm = document.getElementById('loan-form');
    if (!applicationForm) return;

    const productInput = applicationForm.querySelector('[name="product"]');
    const product = productInput?.selectedOptions?.[0];
    if (!product || !product.value) return;

    const applicationField = name => applicationForm.querySelector(`[name="${name}"]`);
    const amount = applicationField('principal')?.value;
    const rate = product.dataset.rate;
    const term = applicationField('term_months')?.value;
    const frequency = applicationField('frequency')?.value;
    const method = applicationField('interest_method')?.value || product.dataset.method;

    if (amount) amountInput.value = amount;
    if (rate) rateInput.value = rate;
    if (term) termInput.value = term;
    if (frequencyInput.querySelector(`option[value="${frequency}"]`)) {
      frequencyInput.value = frequency;
    }
    if (methodInput.querySelector(`option[value="${method}"]`)) {
      methodInput.value = method;
    }
  }

  async function updateEstimate() {
    if (activeRequest) activeRequest.abort();

    const principal = Number(amountInput.value);
    const monthlyRate = Number(rateInput.value);
    const termMonths = Number(termInput.value);
    if (
      !Number.isFinite(principal) || principal <= 0 ||
      !Number.isFinite(monthlyRate) || monthlyRate < 0 ||
      !Number.isInteger(termMonths) || termMonths < 1 || termMonths > 60
    ) {
      results.hidden = true;
      showError('Enter an amount above zero, a valid rate, and a term from 1 to 60 months.');
      return;
    }

    errorMessage.hidden = true;
    const params = calculatorParams();
    const controller = new AbortController();
    activeRequest = controller;
    panel.setAttribute('aria-busy', 'true');

    try {
      const response = await fetch(`${widget.dataset.previewUrl}?${params}`, {
        headers: { Accept: 'application/json' },
        signal: controller.signal,
      });
      if (!response.headers.get('content-type')?.includes('application/json')) {
        throw new Error('Refresh the page to continue using the calculator.');
      }
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Unable to calculate this estimate.');
      if (activeRequest !== controller) return;

      document.getElementById('loan-calc-average').textContent = formatMoney(result.average_payment);
      document.getElementById('loan-calc-interest').textContent = formatMoney(result.total_interest);
      document.getElementById('loan-calc-total').textContent = formatMoney(result.total_repayable);
      document.getElementById('loan-calc-first').textContent = formatMoney(result.first_payment);
      document.getElementById('loan-calc-final').textContent = formatMoney(result.final_payment);
      document.getElementById('loan-calc-period-count').textContent = result.period_count;
      results.hidden = false;
    } catch (error) {
      if (error.name === 'AbortError') return;
      results.hidden = true;
      showError(error.message || 'Unable to calculate right now. Try again.');
    } finally {
      if (activeRequest === controller) {
        activeRequest = null;
        panel.removeAttribute('aria-busy');
      }
    }
  }

  function scheduleEstimate() {
    window.clearTimeout(debounceTimer);
    debounceTimer = window.setTimeout(updateEstimate, 220);
  }

  function setOpen(open) {
    panel.hidden = !open;
    trigger.setAttribute('aria-expanded', String(open));
    if (open) {
      syncApplicationTerms();
      updateEstimate();
      amountInput.focus();
    } else {
      window.clearTimeout(debounceTimer);
      if (activeRequest) activeRequest.abort();
      trigger.focus();
    }
  }

  trigger.addEventListener('click', () => setOpen(panel.hidden));
  closeButton.addEventListener('click', () => setOpen(false));
  shareButton.addEventListener('click', shareSchedule);
  [amountInput, rateInput, termInput, frequencyInput, methodInput]
    .forEach(input => input.addEventListener('input', scheduleEstimate));
  [frequencyInput, methodInput].forEach(input => input.addEventListener('change', scheduleEstimate));

  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !panel.hidden) setOpen(false);
  });
  document.addEventListener('click', event => {
    if (!panel.hidden && !widget.contains(event.target)) setOpen(false);
  });
})();