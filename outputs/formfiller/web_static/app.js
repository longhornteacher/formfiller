(() => {
  'use strict';
  const root = document.querySelector('#view-root');
  const notice = document.querySelector('#notice');
  const dialog = document.querySelector('#form-dialog');
  const confirmDialog = document.querySelector('#confirm-dialog');
  const setupForm = document.querySelector('#form-setup');
  const state = { csrf: '', view: 'forms', forms: [], selectedId: null, removeId: null, inspection: null, session: {} };
  const viewNames = { forms: 'Forms', today: 'Today', history: 'History', sync: 'Sync', readiness: 'Readiness' };
  const safeText = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const dateLabel = value => value ? safeText(value) : '—';
  const showNotice = (message, kind = 'info') => {
    notice.textContent = message;
    notice.className = `notice ${kind}`;
    notice.hidden = false;
  };
  const clearNotice = () => { notice.hidden = true; notice.textContent = ''; };
  const request = async (path, options = {}) => {
    const method = options.method || 'GET';
    const headers = { 'Accept': 'application/json', ...(options.body ? {'Content-Type':'application/json'} : {}), ...(path !== '/api/session' ? {'X-FormFiller-Token': state.csrf} : {}), ...options.headers };
    const response = await fetch(path, { ...options, method, headers, body: options.body ? JSON.stringify(options.body) : undefined, credentials: 'same-origin', cache: 'no-store' });
    let data = {};
    try { data = await response.json(); } catch (_) { /* handled as a sanitized request failure */ }
    if (!response.ok) {
      const error = data?.error;
      const requestError = new Error(error?.message || `Request failed (${response.status})`);
      requestError.code = error?.code || '';
      requestError.status = response.status;
      throw requestError;
    }
    return data;
  };
  const buttonBusy = (button, busy, text) => { if (!button) return; button.disabled = busy; if (text) button.textContent = text; };
  const loadForms = async () => { const data = await request('/api/forms'); state.forms = Array.isArray(data.forms) ? data.forms : []; if (!state.forms.some(form => form.id === state.selectedId)) state.selectedId = state.forms[0]?.id || null; renderForms(); };
  const nav = document.querySelector('.nav-list');
  nav.addEventListener('click', event => {
    const button = event.target.closest('[data-view]');
    if (!button) return;
    state.view = button.dataset.view;
    nav.querySelectorAll('.nav-item').forEach(item => item.classList.toggle('active', item === button));
    document.querySelector('#crumb-current').textContent = viewNames[state.view];
    clearNotice();
    loadView().catch(error => showNotice(error.message, 'error'));
  });
  document.querySelector('#refresh-button').addEventListener('click', () => { clearNotice(); loadView().catch(error => showNotice(error.message, 'error')); });
  const loadView = async () => {
    if (state.view === 'forms') return loadForms();
    const data = await request(`/api/${state.view}`);
    if (state.view === 'today') renderToday(data);
    else if (state.view === 'history') renderHistory(data);
    else if (state.view === 'readiness') renderReadiness(data);
    else if (state.view === 'sync') renderSync(data);
  };
  const modeLabel = mode => /demo/i.test(String(mode || '')) ? 'Demo · synthetic data' : 'Private local workspace';
  const renderForms = () => {
    const forms = state.forms;
    const selected = forms.find(form => form.id === state.selectedId);
    root.innerHTML = `<div class="page-heading"><div><h1>Forms</h1><p>Choose a form to review or update its saved answers.</p></div><button class="button primary" id="add-form"><span aria-hidden="true">＋</span> Add form</button></div>
      ${forms.length ? `<div class="forms-workspace"><section class="form-list-panel" aria-label="Saved forms"><div class="list-heading"><h2>Saved forms</h2><span>${forms.length}</span></div><div class="compact-form-list">${forms.map(formListRow).join('')}</div></section><section class="editor-panel" aria-label="Form editor">${selected ? formEditor(selected) : ''}</section></div>` : `<div class="empty-state"><div class="empty-icon" aria-hidden="true">＋</div><h2>No forms saved yet</h2><p>Add a form to inspect its questions and prepare answers for review.</p><button class="button primary" id="empty-add-form">Add form</button></div>`}`;
    root.querySelector('#add-form')?.addEventListener('click', () => openCreate());
    root.querySelector('#empty-add-form')?.addEventListener('click', () => openCreate());
    root.querySelectorAll('[data-select-form]').forEach(button => button.addEventListener('click', () => { state.selectedId = button.dataset.selectForm; renderForms(); }));
    if (selected) renderAnswerFields(selected.schema || {questions:[]}, selected.answers || {}, '#inline-answer-fields');
    root.querySelector('#save-inline-form')?.addEventListener('click', saveInlineForm);
    root.querySelector('#remove-inline-form')?.addEventListener('click', () => askRemove(selected.id));
    root.querySelector('#reviewed-answers')?.addEventListener('change', updateApprovalState);
    root.querySelector('#inline-answer-fields')?.addEventListener('input', updateApprovalState);
    root.querySelector('#inline-answer-fields')?.addEventListener('change', updateApprovalState);
    root.querySelector('#editor-name')?.addEventListener('input', updateApprovalState);
    root.querySelector('#approve-answers')?.addEventListener('click', approveAnswers);
    updateApprovalState();
  };
  const formListRow = form => {
    const questions = normalizedQuestions(form.schema).length;
    const needsReview = Boolean(form.review_required);
    return `<button class="form-list-row ${form.id === state.selectedId ? 'selected' : ''}" data-select-form="${safeText(form.id)}"><span class="form-list-name">${safeText(form.name || 'Untitled form')}</span><span class="form-list-sub">${questions} ${questions===1?'question':'questions'} · ${needsReview?'Needs review':'Configured'}</span></button>`;
  };
  const openCreate = () => {
    state.inspection = null;
    setupForm.reset();
    document.querySelector('#dialog-title').textContent = 'Add a form';
    document.querySelector('#details-step').hidden = false;
    document.querySelector('#answers-step').hidden = true;
    updateSteps(1);
    document.querySelector('#inspect-button').disabled = false;
    dialog.showModal();
    document.querySelector('#form-name').focus();
  };
  const formEditor = form => {
    const review = form.review_required ? `<div class="review-prompt"><strong>Review these saved answers before use.</strong><label><input id="reviewed-answers" type="checkbox"> I reviewed these saved answers</label><button id="approve-answers" class="button secondary" disabled>Approve saved answers</button><span id="review-save-help" class="review-help" hidden>Save changes before reviewing these answers.</span>${form.review_token ? '' : '<span class="review-help">Current review approval is unavailable. Refresh the form before approving.</span>'}</div>` : '';
    return `<div class="editor-heading"><div><p class="eyebrow">FORM EDITOR</p><h2>${safeText(form.name || 'Untitled form')}</h2><p class="editor-subtitle">Update the saved answers for this form.</p></div><button class="text-action remove" id="remove-inline-form">Remove form</button></div><div class="inline-name"><label for="editor-name">Form name</label><input id="editor-name" type="text" maxlength="120" value="${safeText(form.name || '')}"></div><div id="inline-answer-fields" class="answer-fields"></div>${review}<div class="editor-actions"><span class="editor-save-status" id="editor-save-status" aria-live="polite"></span><button id="save-inline-form" class="button primary">Save changes</button></div>`;
  };
  const canonicalAnswer = value => Array.isArray(value) ? [...value].sort() : (value ?? '');
  const editorIsDirty = form => {
    const name = document.querySelector('#editor-name')?.value.trim() ?? form.name ?? '';
    if (name !== (form.name || '')) return true;
    const fields = [...document.querySelectorAll('#inline-answer-fields [data-answer]')];
    const ids = [...new Set(fields.map(field => field.dataset.answer))];
    const current = collectAnswers('#inline-answer-fields');
    return ids.some(id => JSON.stringify(canonicalAnswer(current[id])) !== JSON.stringify(canonicalAnswer(form.answers?.[id])));
  };
  const updateApprovalState = () => {
    const form = state.forms.find(item => item.id === state.selectedId);
    const checkbox = document.querySelector('#reviewed-answers');
    const button = document.querySelector('#approve-answers');
    if (!form?.review_required || !checkbox || !button) return;
    const dirty = editorIsDirty(form);
    if (dirty) checkbox.checked = false;
    checkbox.disabled = dirty || !form.review_token;
    button.disabled = dirty || !checkbox.checked || !form.review_token;
    const help = document.querySelector('#review-save-help');
    if (help) help.hidden = !dirty;
  };
  const approveAnswers = async event => {
    const button = event.currentTarget;
    const form = state.forms.find(item => item.id === state.selectedId);
    if (!form?.review_token || editorIsDirty(form) || !document.querySelector('#reviewed-answers')?.checked) {
      updateApprovalState();
      return;
    }
    buttonBusy(button, true, 'Approving…');
    try {
      await request(`/api/forms/${encodeURIComponent(form.id)}/approve`, {method:'POST', body:{review_token:form.review_token}});
      showNotice('Saved answers approved for this form.', 'success');
      await loadForms();
    } catch (error) {
      if (/stale|expired|changed/i.test(error.code || '')) {
        showNotice('This form changed since it was reviewed. The latest answers have been reloaded.', 'info');
        await loadForms();
      } else { showNotice(error.message, 'error'); button.disabled = false; button.textContent = 'Approve saved answers'; }
    }
  };
  const saveInlineForm = async event => {
    const button = event.currentTarget;
    const form = state.forms.find(item => item.id === state.selectedId);
    if (!form) return;
    buttonBusy(button, true, 'Saving…');
    try {
      await request(`/api/forms/${encodeURIComponent(form.id)}`, {method:'PUT', body:{name:document.querySelector('#editor-name').value.trim() || form.name, url:form.url, answers:collectAnswers('#inline-answer-fields')}});
      document.querySelector('#editor-save-status').textContent = 'Saved locally';
      showNotice('Form answers saved.', 'success');
      await loadForms();
    } catch (error) { showNotice(error.message, 'error'); }
    finally { button.disabled = false; button.textContent = 'Save changes'; }
  };
  const updateSteps = current => document.querySelectorAll('.step').forEach(step => { const n = Number(step.dataset.step); step.classList.toggle('current', n === current); step.classList.toggle('done', n < current); });
  const closeDialog = () => { dialog.close(); document.querySelector('#form-name').readOnly = false; document.querySelector('#form-url').readOnly = false; document.querySelector('#back-button').hidden = false; document.querySelector('#save-form-button').textContent = 'Save form'; };
  document.querySelectorAll('[data-close-dialog]').forEach(button => button.addEventListener('click', closeDialog));
  document.querySelector('#inspect-button').addEventListener('click', async event => {
    clearNotice();
    const button = event.currentTarget;
    const name = document.querySelector('#form-name').value.trim();
    const url = document.querySelector('#form-url').value.trim();
    if (!name || !url) { showNotice('Enter a form name and URL to continue.', 'error'); return; }
    buttonBusy(button, true, 'Inspecting…');
    try {
      const result = await request('/api/forms/inspect', {method:'POST', body:{name,url}});
      state.inspection = {...result, name, url, answers:{}};
      document.querySelector('#details-step').hidden = true;
      document.querySelector('#answers-step').hidden = false;
      document.querySelector('#dialog-title').textContent = 'Configure answers';
      document.querySelector('#inspection-summary').textContent = `${Array.isArray(result.schema?.questions) ? result.schema.questions.length : 0} question(s) found. Review the fields below and save when ready.`;
      document.querySelector('#save-form-button').textContent = 'Save form';
      renderAnswerFields(result.schema || {questions:[]}, {});
      updateSteps(2);
    } catch (error) { showNotice(error.message, 'error'); }
    finally { button.disabled = false; button.innerHTML = 'Inspect form <span aria-hidden="true">→</span>'; }
  });
  document.querySelector('#back-button').addEventListener('click', () => {
    document.querySelector('#answers-step').hidden = true;
    document.querySelector('#details-step').hidden = false;
    document.querySelector('#dialog-title').textContent = 'Add a form';
    updateSteps(1);
  });
  const normalizedQuestions = schema => Array.isArray(schema?.questions) ? schema.questions : Array.isArray(schema?.fields) ? schema.fields : Array.isArray(schema) ? schema : [];
  const questionId = (question, index) => question.id || `q${index}`;
  const inputValue = value => typeof value === 'string' ? value : value && typeof value === 'object' ? String(value.value ?? '') : '';
  const renderAnswerFields = (schema, answers, selector = '#answer-fields') => {
    const host = document.querySelector(selector);
    const questions = normalizedQuestions(schema);
    if (!questions.length) { host.innerHTML = '<div class="empty-state"><p>No editable questions were found in the inspected schema.</p></div>'; return; }
    host.innerHTML = questions.map((question,index) => answerField(question, questionId(question,index), answers?.[questionId(question,index)])).join('');
  };
  const answerField = (question, id, answer) => {
    const label = safeText(question.label || question.title || `Question ${id}`);
    const required = question.required ? '<span class="required-mark" aria-label="required">*</span>' : '';
    const type = String(question.type || question.kind || 'text').toLowerCase();
    const options = Array.isArray(question.options) ? question.options : Array.isArray(question.controls) ? question.controls.flatMap(control => control.options || (control.label ? [control.label] : [])) : [];
    let control = '';
    if (type === 'date') {
      const answerDate = answer?.kind === 'date' ? (answer.value || 'Set when the form runs') : 'Set when the form runs';
      control = `<div class="answer-input" aria-readonly="true">${safeText(answerDate)}</div><div class="answer-help">Run date · filled from the approved school calendar</div>`;
    } else if (type === 'choice' || type === 'radio' || type === 'select') {
      const selected = inputValue(answer);
      control = `<select class="answer-select" data-answer="${safeText(id)}"><option value="">Choose an answer</option>${options.map(option => `<option value="${safeText(option)}" ${String(option) === selected ? 'selected' : ''}>${safeText(option)}</option>`).join('')}</select>`;
    } else if (type === 'multichoice' || type === 'checkboxes' || type === 'multi_choice') {
      const selected = Array.isArray(answer) ? answer : [];
      control = `<div class="choice-list">${options.map((option,index) => `<label class="choice-item"><input type="checkbox" data-answer="${safeText(id)}" value="${safeText(option)}" ${selected.includes(option) ? 'checked' : ''}><span>${safeText(option)}</span></label>`).join('')}</div>`;
    } else if (type === 'matrix') {
      const selected = Array.isArray(answer) ? answer : [];
      control = `<div class="choice-list">${options.map(option => `<label class="choice-item"><input type="checkbox" data-answer="${safeText(id)}" value="${safeText(option)}" ${selected.includes(option) ? 'checked' : ''}><span>${safeText(option)}</span></label>`).join('')}</div>`;
    } else {
      const value = inputValue(answer);
      const multiline = (question.multiline || question.paragraph || question.type === 'paragraph');
      control = multiline ? `<textarea class="answer-textarea" data-answer="${safeText(id)}" rows="3">${safeText(value)}</textarea>` : `<input class="answer-input" type="text" data-answer="${safeText(id)}" value="${safeText(value)}" autocomplete="off">`;
    }
    return `<fieldset class="answer-group"><legend>${label}${required}</legend>${control}</fieldset>`;
  };
  const collectAnswers = (selector = '') => {
    const answers = {};
    const scope = selector ? document.querySelector(selector) : document;
    scope.querySelectorAll('[data-answer]').forEach(input => {
      const id = input.dataset.answer;
      if (input.type === 'checkbox') {
        if (!Array.isArray(answers[id])) answers[id] = [];
        if (input.checked) answers[id].push(input.value);
      } else answers[id] = input.value;
    });
    return answers;
  };
  document.querySelector('#save-form-button').addEventListener('click', async event => {
    clearNotice();
    const button = event.currentTarget;
    if (!state.inspection) return;
    buttonBusy(button, true, 'Saving…');
    const answers = collectAnswers('#answer-fields');
    const name = document.querySelector('#form-name').value.trim() || state.inspection.name;
    try {
      await request('/api/forms', {method:'POST', body:{name, url:state.inspection.url, schema:state.inspection.schema, answers, inspect_token:state.inspection.inspect_token}});
      closeDialog();
      showNotice('Form saved. Review its readiness before use.', 'success');
      await loadForms();
    } catch (error) { showNotice(error.message, 'error'); }
    finally { button.disabled = false; button.textContent = 'Save form'; }
  });
  const askRemove = id => { state.removeId = id; confirmDialog.showModal(); };
  document.querySelectorAll('[data-close-confirm]').forEach(button => button.addEventListener('click', () => confirmDialog.close()));
  document.querySelector('#confirm-remove').addEventListener('click', async event => {
    const button = event.currentTarget; buttonBusy(button,true,'Removing…');
    try { await request(`/api/forms/${encodeURIComponent(state.removeId)}`,{method:'DELETE'}); confirmDialog.close(); showNotice('Form removed.','success'); await loadForms(); }
    catch(error){ showNotice(error.message,'error'); }
    finally { button.disabled=false; button.textContent='Remove form'; state.removeId=null; }
  });
  const statusClass = status => /ready|ok|pass|success|complete|synced|submitted/i.test(String(status)) ? 'good' : /fail|blocked|error|missing|review|stale|uncertain/i.test(String(status)) ? 'warn' : '';
  const safeCode = item => item.code ? `<span class="tag">${safeText(item.code)}</span>` : '';
  const renderToday = data => {
    const items = Array.isArray(data.items) ? data.items : [];
    root.innerHTML = `<div class="page-heading"><div><h1>Today</h1><p>Scheduled activity and current form status for ${dateLabel(data.date)}.</p><p class="today-mode">${safeText(modeLabel(data.mode || state.session.mode))}</p></div><button id="run-today" class="button primary" ${data.can_run === false ? 'disabled' : ''}>Run today's forms</button></div><div class="today-run-note" id="today-run-note" ${data.can_run === false ? '' : 'hidden'}>A run is unavailable until local readiness checks allow it.</div><div class="today-meta"><span><b>Date</b> ${dateLabel(data.date)}</span><span><b>Forms</b> ${items.length}</span></div><div class="section-title-row"><h2>Today's forms</h2></div>${items.length ? `<div class="row-list">${items.map(item=>`<div class="list-row"><div><strong>${safeText(item.name || 'Form')}</strong></div><span class="tag ${statusClass(item.status)}">${safeText(item.status || 'Pending')}</span></div>`).join('')}</div>` : `<div class="empty-state"><div class="empty-icon" aria-hidden="true">◷</div><h2>No activity today</h2><p>The local runner and calendar status will appear here when available.</p></div>`}`;
    root.querySelector('#run-today').addEventListener('click', async event => {
      const button = event.currentTarget;
      clearNotice(); buttonBusy(button, true, 'Starting…');
      try { await request('/api/run', {method:'POST', body:{}}); showNotice('Run finished. Refreshing today’s status.','success'); const updated=await request('/api/today'); renderToday(updated); }
      catch (error) { showNotice(error.message, 'error'); button.disabled=false; button.textContent="Run today's forms"; }
    });
  };
  const renderHistory = data => {
    const items = Array.isArray(data.items) ? data.items : [];
    root.innerHTML = `<div class="page-heading"><div><h1>History</h1><p>Recent activity recorded by the local runner.</p></div></div>${items.length ? `<div class="row-list">${items.map(item=>`<div class="list-row"><div><strong>${dateLabel(item.date)}</strong><small>${Object.entries(item.counts || {}).map(([key,value])=>`${safeText(key)}: ${safeText(value)}`).join(' · ') || 'No run details'}</small></div>${item.status ? `<span class="tag ${statusClass(item.status)}">${safeText(item.status)}</span>` : ''}</div>`).join('')}</div>` : `<div class="empty-state"><div class="empty-icon" aria-hidden="true">↺</div><h2>No history yet</h2><p>Completed local activity will be listed here.</p></div>`}`;
  };
  const renderReadiness = data => {
    const items = Array.isArray(data.items) ? data.items : [];
    root.innerHTML = `<div class="page-heading"><div><h1>Readiness</h1><p>Local checks required before a run can proceed.</p></div><span class="tag ${data.ready ? 'good' : 'warn'}">${data.ready ? 'Ready' : 'Check required'}</span></div>${!data.ready ? '<div class="notice-box">One or more local prerequisites need attention. Review the checks below for their current status.</div>' : '<div class="notice-box good">All reported prerequisites are currently ready.</div>'}<div class="content-panel"><h2 class="panel-title">Environment checks</h2><div class="data-list">${items.map(item=>`<div class="data-row"><div class="data-label">${safeText(item.label || 'Check')}</div><div class="data-value">${safeText(item.status || 'Unknown')} ${safeCode(item)}</div></div>`).join('') || '<div class="data-row"><div class="data-value muted">No check details available.</div></div>'}</div></div>`;
  };
  const renderSync = data => {
    const items = Array.isArray(data.items) ? data.items : [];
    root.innerHTML = `<div class="page-heading"><div><h1>Sync</h1><p>Check local sources and configuration status.</p></div><button id="sync-check" class="button primary">Check now</button></div><div class="content-panel"><div class="section-title-row flush-top"><h2>Source status</h2><span class="count-label">${data.checked_at ? `Checked ${safeText(data.checked_at)}` : 'Not checked this session'}</span></div><div class="data-list">${items.map(item=>`<div class="data-row"><div class="data-label">${safeText(item.label || 'Source')}</div><div class="data-value">${safeText(item.status || 'Unknown')} ${safeCode(item)}</div></div>`).join('') || '<div class="data-row"><div class="data-value muted">No source status available.</div></div>'}</div></div>`;
    root.querySelector('#sync-check').addEventListener('click', async event => {
      const button=event.currentTarget; buttonBusy(button,true,'Checking…');
      try { const result=await request('/api/sync/check',{method:'POST',body:{}}); renderSync(result); showNotice('Local source check completed.','success'); }
      catch(error){ showNotice(error.message,'error'); button.disabled=false; button.textContent='Check now'; }
    });
  };
  const renderWorkspaceSetup = () => {
    root.innerHTML = `<div class="page-heading"><div><h1>Choose a private workspace</h1><p>FormFiller stores its private data in a folder you select on this computer.</p></div></div><div class="setup-panel"><div class="empty-icon" aria-hidden="true">⌂</div><h2>Keep your workspace on this computer</h2><p>Your form settings and saved answers stay in the chosen local folder. FormFiller will not show its path in this app.</p><button class="button primary" id="choose-workspace">Choose folder</button><div class="workspace-choice-status" id="workspace-choice-status" aria-live="polite"></div></div>`;
    root.querySelector('#choose-workspace').addEventListener('click', async event => {
      const button = event.currentTarget; buttonBusy(button, true, 'Opening folder picker…');
      try {
        const result = await request('/api/workspace/choose', {method:'POST', body:{}});
        if (result.cancelled) { button.disabled=false; button.textContent='Choose folder'; return; }
        const displayName = result.workspace_name || 'Private workspace';
        root.querySelector('#workspace-choice-status').textContent = `${displayName} selected. Loading your forms…`;
        const session = await request('/api/session');
        state.session = session;
        state.csrf = session.csrf_token || state.csrf;
        document.querySelector('#mode-badge').innerHTML = `<span class="local-dot"></span>${safeText(modeLabel(session.mode))}`;
        if (!session.needs_setup) { state.view='forms'; nav.querySelectorAll('.nav-item').forEach(item => item.classList.toggle('active', item.dataset.view === 'forms')); await loadForms(); showNotice(`${displayName} selected.`, 'success'); }
        else { button.disabled=false; button.textContent='Choose folder'; }
      } catch (error) { showNotice(error.message, 'error'); button.disabled=false; button.textContent='Choose folder'; }
    });
  };
  document.addEventListener('DOMContentLoaded', async () => {
    try {
      const session=await request('/api/session');
      state.session = session;
      state.csrf = session.csrf_token || '';
      document.querySelector('#mode-badge').innerHTML = `<span class="local-dot"></span>${safeText(modeLabel(session.mode))}`;
      if (session.needs_setup) renderWorkspaceSetup(); else await loadForms();
    } catch(error) {
      showNotice(error.message || 'The local FormFiller service could not be reached.','error');
      root.innerHTML='<div class="empty-state"><div class="empty-icon" aria-hidden="true">!</div><h2>Unable to load workspace</h2><p>Check that the local FormFiller service is running, then refresh.</p><button class="button secondary" id="try-again">Try again</button></div>';
      root.querySelector('#try-again').addEventListener('click', () => location.reload());
    }
  });
})();
