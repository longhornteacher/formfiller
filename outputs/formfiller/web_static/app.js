(() => {
  'use strict';
  const root = document.querySelector('#view-root');
  const notice = document.querySelector('#notice');
  const dialog = document.querySelector('#form-dialog');
  const confirmDialog = document.querySelector('#confirm-dialog');
  const setupForm = document.querySelector('#form-setup');
  const state = { course: '', csrf: '', view: 'forms', forms: [], selectedId: null, removeId: null, inspection: null, session: {}, skyward: null, skywardCourses: [] };
  const viewNames = { forms: 'Forms', today: 'Today', attendance: 'Attendance Preview', history: 'History', sync: 'Sync', readiness: 'Readiness', setup: 'Setup', guide: 'Teacher Guide', skyward: 'Skyward' };
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
  const navigateView = view => {
    state.view = view;
    nav.querySelectorAll('.nav-item').forEach(item => item.classList.toggle('active', item.dataset.view === view));
    document.querySelector('#crumb-current').textContent = viewNames[view] || 'Workspace';
    clearNotice();
    loadView().catch(error => showNotice('This view could not be loaded. Refresh and try again.', 'error'));
  };
  nav.addEventListener('click', event => {
    const button = event.target.closest('[data-view]');
    if (!button) return;
    navigateView(button.dataset.view);
  });
  document.querySelector('#refresh-button').addEventListener('click', () => { clearNotice(); loadView().catch(error => showNotice(error.message, 'error')); });
  const loadView = async () => {
    if (state.view === 'forms') return loadForms();
    if (state.view === 'setup') return renderSetup();
    if (state.view === 'guide') return renderGuide();
    if (state.view === 'skyward') return loadSkyward();
    const data = await request(`/api/${state.view}`);
    if (state.view === 'today') renderToday(data);
    else if (state.view === 'attendance') renderAttendance(data);
    else if (state.view === 'history') renderHistory(data);
    else if (state.view === 'readiness') renderReadiness(data);
    else if (state.view === 'sync') renderSync(data);
  };
  const modeLabel = mode => /demo/i.test(String(mode || '')) ? 'Demo · synthetic data' : 'Private local workspace';
  const renderForms = () => {
    const forms = state.forms;
    const selected = forms.find(form => form.id === state.selectedId);
    root.innerHTML = `<div class="page-heading"><div><h1>Forms</h1><p>Each form has its own template responses. Save them, then explicitly review them before use.</p></div><button class="button primary" id="add-form"><span aria-hidden="true">＋</span> Add form</button></div><div class="notice-box"><strong>First time?</strong> Add a form, inspect its questions, enter template responses, save, then review. These answers are reused each time this form runs. Date fields use the run date. <button class="text-action" id="forms-guide">Read the quick start</button></div>
      ${forms.length ? `<div class="forms-workspace"><section class="form-list-panel" aria-label="Saved forms"><div class="list-heading"><h2>Saved forms</h2><span>${forms.length}</span></div><div class="compact-form-list">${forms.map(formListRow).join('')}</div></section><section class="editor-panel" aria-label="Form editor">${selected ? formEditor(selected) : ''}</section></div>` : `<div class="empty-state"><div class="empty-icon" aria-hidden="true">＋</div><h2>No forms saved yet</h2><p>Add a form to inspect its questions and prepare template responses for review.</p><button class="button primary" id="empty-add-form">Add form</button><button class="button secondary" id="open-setup">Continue setup</button></div>`}`;
    root.querySelector('#add-form')?.addEventListener('click', () => openCreate());
    root.querySelector('#empty-add-form')?.addEventListener('click', () => openCreate());
    root.querySelector('#open-setup')?.addEventListener('click', () => navigateView('setup'));
    root.querySelector('#forms-guide')?.addEventListener('click', () => navigateView('guide'));
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
    return `<button class="form-list-row ${form.id === state.selectedId ? 'selected' : ''}" data-select-form="${safeText(form.id)}"><span class="form-list-name">${safeText(form.name || 'Untitled form')}</span><span class="form-list-sub">${questions} ${questions===1?'question':'questions'} · ${needsReview?'Saved — review needed':'Reviewed and ready'}</span></button>`;
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
    const review = form.review_required ? `<div class="review-prompt"><strong>Saved — review needed.</strong><p>Read each template response and confirm it is correct. Editing a response means it must be saved and reviewed again.</p><label><input id="reviewed-answers" type="checkbox"> I reviewed these saved template responses</label><button id="approve-answers" class="button secondary" disabled>Mark reviewed</button><span id="review-save-help" class="review-help" hidden>Save changes before reviewing these responses.</span>${form.review_token ? '' : '<span class="review-help">Current review approval is unavailable. Refresh the form before reviewing.</span>'}</div>` : `<div class="notice-box good">Reviewed and ready. These template responses belong to this form and will be reused each time it runs.</div>`;
    return `<div class="editor-heading"><div><p class="eyebrow">FORM EDITOR</p><h2>${safeText(form.name || 'Untitled form')}</h2><p class="editor-subtitle">Template responses are saved for this form only. These answers are reused each time this form runs. Date fields use the run date.</p></div><button class="text-action remove" id="remove-inline-form">Remove form</button></div><div class="inline-name"><label for="editor-name">Form name</label><input id="editor-name" type="text" maxlength="120" value="${safeText(form.name || '')}"></div><div id="inline-answer-fields" class="answer-fields"></div>${review}<div class="editor-actions"><span class="editor-save-status" id="editor-save-status" aria-live="polite"></span><button id="save-inline-form" class="button primary">Save template responses</button></div>`;
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
      showNotice('Template responses saved — review needed.', 'success');
      await loadForms();
    } catch (error) {
      const guidance = readinessCopy({code:error.code});
      showNotice(error.code && error.code !== 'request_failed' ? guidance[0] : 'The form could not be inspected. Check the URL and local readiness, then try again.', 'error');
    }
    finally { button.disabled = false; button.textContent = 'Save template responses'; }
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
      document.querySelector('#inspection-summary').textContent = `${Array.isArray(result.schema?.questions) ? result.schema.questions.length : 0} question(s) found. Enter template responses, save, then review them. Unsupported question types are left unresolved and cannot pass schema approval.`;
      document.querySelector('#save-form-button').textContent = 'Save form';
      renderAnswerFields(result.schema || {questions:[]}, {});
      updateSteps(2);
    } catch (error) {
      const guidance = readinessCopy({code:error.code});
      showNotice(error.code && error.code !== 'request_failed' ? guidance[0] : 'The form could not be inspected. Check the URL and local readiness, then try again.', 'error');
    }
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
    } else if (type === 'unsupported' || question.supported === false) {
      control = `<div class="notice-box">This question type is not supported for template responses. No answer was guessed. Resolve it through the reviewed schema process before this form can be approved or used.</div>`;
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
      showNotice('Template responses saved — review needed.', 'success');
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
  const markLabels = { present: 'Here', absent: 'Absent', tardy: 'Tardy' };
  const renderAttendance = data => {
    const students = Array.isArray(data.students) ? data.students : [];
    const counts = data.counts || {};
    const locked = Boolean(data.submitted);
    const postingUnavailable = (data.mode || state.session.mode) === 'private';
    const courses = Array.isArray(data.courses) ? data.courses : [];
    const chosen = state.course && courses.some(course => course.id === state.course) ? state.course : (data.course || courses[0]?.id || '');
    const picker = courses.length ? `<label class="course-picker" for="course-select">Class</label><select id="course-select" class="answer-select" ${locked ? 'disabled' : ''}>${courses.map(course => `<option value="${safeText(course.id)}" ${course.id === chosen ? 'selected' : ''}>${safeText(course.name)}${course.period ? ` (${safeText(course.period)})` : ''}</option>`).join('')}</select>` : '';
    const rows = students.map(student => `<div class="student-row ${safeText(student.mark)}"><div class="student-name"><strong>${safeText(student.name)}</strong>${student.suggested === 'absent' ? '<span class="tag warn j-tag">J rule</span>' : ''}${Object.keys(student.details || {}).length ? `<small>${Object.entries(student.details).map(([key, value]) => `${safeText(key)} ${safeText(value)}`).join(' · ')}</small>` : ''}</div><div class="mark-group" role="group" aria-label="Attendance for ${safeText(student.name)}">${Object.entries(markLabels).map(([mark, label]) => `<button type="button" class="mark-button ${mark} ${student.mark === mark ? 'on' : ''}" data-student="${safeText(student.id)}" data-mark="${mark}" aria-pressed="${student.mark === mark}" ${locked ? 'disabled' : ''}>${label}</button>`).join('')}</div></div>`).join('');
    const demoMode = (data.mode || state.session.mode) === 'demo';
    root.innerHTML = `<div class="page-heading"><div><h1>Attendance Preview</h1><p>Review the local roster and marks for ${dateLabel(data.date)}. Posting has not been verified.</p><p class="today-mode">${safeText(modeLabel(data.mode || state.session.mode))}</p></div><div class="heading-actions">${picker}<button id="load-roster" class="button primary" ${locked || !courses.length ? 'disabled' : ''}>${students.length ? 'Reload roster' : 'Load roster'}</button></div></div>${postingUnavailable ? '<div class="notice-box">Send attendance is disabled in the private app while Skyward posting is unavailable. Review every mark; this preview does not post attendance.</div>' : '<div class="notice-box">This is a synthetic preview. The demo action only simulates a result and does not send attendance.</div>'}${courses.length ? '' : '<div class="notice-box">No Skyward classes are configured yet. Open Skyward settings to add a class in the private workspace.</div><button type="button" class="button secondary" data-go="skyward">Skyward settings</button>'}${students.length ? `<div class="today-meta"><span><b>Students</b> ${students.length}</span><span><b>Here</b> ${counts.present ?? 0}</span><span><b>Absent</b> ${counts.absent ?? 0}</span><span><b>Tardy</b> ${counts.tardy ?? 0}</span></div><div class="roster-panel">${rows}</div><div class="editor-actions"><span class="editor-save-status" id="attendance-status" aria-live="polite">${locked ? 'Demo preview complete' : 'Preview only'}</span><button id="submit-attendance" class="button primary" ${locked || postingUnavailable ? 'disabled' : ''}>${postingUnavailable ? 'Send attendance' : 'Simulate attendance (demo)'}</button></div>` : `<div class="empty-state"><div class="empty-icon" aria-hidden="true">🍎</div><h2>No roster loaded</h2><p>A J in a neighboring period suggests an absence. Review every mark. Names stay on this computer.</p></div>`}`;
    root.querySelectorAll('[data-go]').forEach(button => button.addEventListener('click', () => navigateView(button.dataset.go)));
    root.querySelector('#course-select')?.addEventListener('change', event => { state.course = event.target.value; });
    root.querySelector('#load-roster')?.addEventListener('click', async event => {
      const button = event.currentTarget; clearNotice(); buttonBusy(button, true, 'Reading Skyward…');
      try { state.course = root.querySelector('#course-select')?.value || ''; renderAttendance(await request('/api/attendance/load', {method:'POST', body:{course: state.course}})); showNotice('Roster loaded.', 'success'); }
      catch (error) { showNotice(error.message, 'error'); button.disabled = false; button.textContent = students.length ? 'Reload roster' : 'Load roster'; }
    });
    root.querySelectorAll('.mark-button').forEach(button => button.addEventListener('click', async () => {
      const marks = {};
      students.forEach(student => { marks[student.id] = student.mark; });
      marks[button.dataset.student] = button.dataset.mark;
      try { renderAttendance(await request('/api/attendance/marks', {method:'POST', body:{marks}})); }
      catch (error) { showNotice(error.message, 'error'); }
    }));
    root.querySelector('#submit-attendance')?.addEventListener('click', async event => {
      const button = event.currentTarget; clearNotice(); buttonBusy(button, true, 'Sending…');
      try { renderAttendance(await request('/api/attendance/submit', {method:'POST', body:{}})); showNotice(demoMode ? 'Synthetic preview simulated. No attendance was sent.' : 'Attendance sent.', 'success'); }
      catch (error) { showNotice(error.message, 'error'); button.disabled = false; button.textContent = demoMode ? 'Simulate attendance (demo)' : 'Send attendance'; }
    });
  };
  const renderHistory = data => {
    const items = Array.isArray(data.items) ? data.items : [];
    root.innerHTML = `<div class="page-heading"><div><h1>History</h1><p>Recent activity recorded by the local runner.</p></div></div>${items.length ? `<div class="row-list">${items.map(item=>`<div class="list-row"><div><strong>${dateLabel(item.date)}</strong><small>${Object.entries(item.counts || {}).map(([key,value])=>`${safeText(key)}: ${safeText(value)}`).join(' · ') || 'No run details'}</small></div>${item.status ? `<span class="tag ${statusClass(item.status)}">${safeText(item.status)}</span>` : ''}</div>`).join('')}</div>` : `<div class="empty-state"><div class="empty-icon" aria-hidden="true">↺</div><h2>No history yet</h2><p>Completed local activity will be listed here.</p></div>`}`;
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
  const readinessCopy = item => {
    const code = String(item?.code || '');
    const messages = {
      workspace_required: ['Choose a private folder to keep form settings and saved responses on this computer.', 'Choose folder', 'setup'],
      missing_calendar: ['The district calendar is not installed in this workspace yet. Follow the calendar setup guide; FormFiller will stop before opening a form until it is valid.', 'Calendar guide', 'guide'],
      calendar_read_error: ['FormFiller could not read the district calendar. Ask the installation manager to restore the reviewed calendar source.', 'Calendar guide', 'guide'],
      workbook_unavailable: ['The approved district calendar source is missing or unreadable. Restore the reviewed source before running.', 'Calendar guide', 'guide'],
      workbook_changed: ['The district calendar source changed since review. It must be reviewed again before use.', 'Calendar guide', 'guide'],
      workbook_schema_changed: ['The district calendar workbook layout changed. Ask the calendar reviewer to check the new SchoolDays sheet before use.', 'Calendar guide', 'guide'],
      workbook_date_mismatch: ['A calendar workbook date does not match its title. Ask the calendar reviewer to correct and review the source.', 'Calendar guide', 'guide'],
      workbook_weekday_mismatch: ['A calendar workbook weekday does not match its date. Ask the calendar reviewer to correct and review the source.', 'Calendar guide', 'guide'],
      workbook_day_type_changed: ['The district calendar contains an unfamiliar day type. Ask the calendar reviewer to check it before use.', 'Calendar guide', 'guide'],
      stale_export: ['The district calendar is out of date. Import and review a fresh district calendar before use.', 'Calendar guide', 'guide'],
      future_export: ['The calendar export is dated in the future. Ask the calendar reviewer to correct its source timestamp and review it again.', 'Calendar guide', 'guide'],
      invalid_max_age: ['The calendar freshness setting is invalid. Ask the installation manager to review the local configuration.', 'Calendar guide', 'guide'],
      workbook_unreadable: ['The district workbook could not be read. Ask the calendar reviewer for a supported, intact workbook.', 'Calendar guide', 'guide'],
      xlsx_dependency_missing: ['Workbook support is missing from this installation. Ask the installation manager to repair the approved local installation.', 'Read installation guide', 'guide'],
      outside_coverage: ['Today is outside the approved calendar coverage. The runner will remain blocked until coverage includes the date.', 'Calendar guide', 'guide'],
      missing_date: ['The approved calendar does not identify this date. Ask for a complete district calendar export and review it.', 'Calendar guide', 'guide'],
      unapproved: ['Your school calendar needs review. A selected file alone does not approve it.', 'Calendar guide', 'guide'],
      invalid_schema: ['The calendar file is not in the supported SchoolDays format. Use the reviewed district calendar workflow.', 'Calendar guide', 'guide'],
      wrong_source: ['This calendar is not from the supported SchoolDays source. Use the district calendar export.', 'Calendar guide', 'guide'],
      schema_review_required: ['These saved answers need review before this form can be used.', 'Review forms', 'forms'],
      schemas_reviewed: ['Saved answers have been reviewed.', 'Review forms', 'forms'],
      verified_by_runner: ['Not yet verified. Sign in manually in the dedicated Edge profile; sign-in is checked when the runner opens the form.', 'Read sign-in guide', 'guide'],
      live_disabled: ['Live use is turned off. Review all requirements and use the separate reviewed configuration process to enable it.', 'Review readiness', 'readiness'],
      demo_only: ['This synthetic demo cannot submit real responses.', 'Review readiness', 'readiness'],
      non_school_day: ['Today is not an approved instructional date. This is an ordinary skip; no response will be submitted.', 'View today', 'today'],
      instructional_date: ['Today is an approved instructional date.', 'View today', 'today'],
      run_locked: ['A run is already in progress. Wait for it to finish, then refresh readiness.', 'Refresh status', 'readiness'],
      idle: ['The local runner is available.', 'View today', 'today'],
      runtime_owner_verified: ['This computer is configured as the local runner.', 'Review readiness', 'readiness'],
      runtime_owner_invalid: ['The local runner could not verify its configured owner. Use the designated computer and ask the installer to repair setup.', 'Read setup guide', 'guide'],
      invalid_coverage: ['The calendar coverage range is invalid. Restore a valid reviewed district source.', 'Calendar guide', 'guide'],
      invalid_timestamp: ['The calendar export timestamp is invalid. Re-export and review the district calendar.', 'Calendar guide', 'guide'],
      invalid_json: ['The calendar file cannot be read as supported data. Use the reviewed district calendar workflow.', 'Calendar guide', 'guide'],
      form_url_invalid: ['Enter a supported school form URL. If the calendar is missing, changed, stale, or does not cover today, resolve that requirement before inspection can open a form.', 'Review readiness', 'readiness'],
      field_type_unsupported: ['This form has a question type that FormFiller cannot save yet. Ask for a reviewed schema update; do not guess an answer.', 'Open Forms', 'forms'],
      answers_invalid: ['One or more template responses do not match the inspected form fields. Review the answers in Forms and try again.', 'Open Forms', 'forms'],
      skyward_config_invalid: ['Check the district login URL and class details. Class IDs must contain 3 to 12 digits.', 'Skyward settings', 'skyward'],
      skyward_url_invalid: ['Use the secure district Skyward login URL supplied by your district.', 'Skyward settings', 'skyward'],
      attendance_posting_unavailable: ['Skyward posting has not been verified. Review attendance marks in Preview; sending is disabled in the private app.', 'Attendance Preview', 'attendance'],
      workspace_not_ready: ['Choose and initialize the private workspace before adding forms.', 'Choose folder', 'setup']
    };
    return messages[code] || (item?.status === 'ready' ? ['This requirement is ready.', 'Review readiness', 'readiness'] : ['This requirement needs attention. Open readiness for the current safe status and follow the local setup guide.', 'Review readiness', 'readiness']);
  };
  const statusPhrase = item => {
    if (item?.code === 'non_school_day') return 'Ordinary non-school-day skip';
    if (item?.status === 'demo' || item?.code === 'demo_only') return 'Demo only';
    if (item?.status === 'ready' || /ready|ok|pass|success|complete|synced|submitted/i.test(String(item?.status || ''))) return 'Ready';
    if (item?.status === 'unknown' || item?.code === 'verified_by_runner') return 'Not yet verified';
    if (item?.status === 'blocked' || item?.status === 'skipped' || /fail|error|missing|review|stale|uncertain/i.test(String(item?.status || ''))) return 'Needs attention';
    return 'Not yet checked';
  };
  const safeStatusRow = item => {
    const [message, action, view] = readinessCopy(item);
    const status = statusPhrase(item);
    return `<div class="data-row"><div><div class="data-label">${safeText(item.label || 'Requirement')} · ${safeText(status)}</div><p>${safeText(message)}</p><button type="button" class="text-action" data-go="${safeText(view)}">${safeText(action)}</button><details><summary>Details</summary><code>${safeText(item.code || 'status_unavailable')}</code></details></div><span class="tag ${status === 'Ready' || status.startsWith('Ordinary') ? 'good' : status === 'Needs attention' || status === 'Demo only' ? 'warn' : ''}">${safeText(status)}</span></div>`;
  };
  const renderReadiness = data => {
    const items = Array.isArray(data.items) ? data.items : [];
    root.innerHTML = `<div class="page-heading"><div><h1>Readiness</h1><p>Current local checks before a run. A ready checklist does not submit anything or turn on live mode.</p></div><span class="tag ${data.ready ? 'good' : 'warn'}">${data.ready ? 'Checks ready' : 'Review needed'}</span></div><div class="content-panel"><h2 class="panel-title">Requirements</h2><div class="data-list">${items.map(safeStatusRow).join('') || '<div class="data-row"><div class="data-value muted">No check details available. Refresh to check again.</div></div>'}</div></div>`;
    root.querySelectorAll('[data-go]').forEach(button => button.addEventListener('click', () => navigateView(button.dataset.go)));
  };
  const renderSetup = async () => {
    const [formsData, readyData] = await Promise.all([request('/api/forms'), request('/api/readiness')]);
    const forms = Array.isArray(formsData.forms) ? formsData.forms : [];
    state.forms = forms;
    if (!forms.some(form => form.id === state.selectedId)) state.selectedId = forms[0]?.id || null;
    const checks = Array.isArray(readyData.items) ? readyData.items : [];
    const find = label => checks.find(item => item.label === label) || {};
    const calendar = find('District calendar');
    const workspace = find('Private workspace');
    const workspaceReady = !state.session.needs_setup && workspace.status !== 'blocked';
    const calendarReady = calendar.status === 'ready' || (calendar.status === 'skipped' && calendar.code === 'non_school_day');
    const reviewedCount = forms.filter(form => !form.review_required).length;
    const formReady = forms.length > 0 && reviewedCount === forms.length;
    const summary = readyData.calendar_summary || {};
    const calendarMeta = summary.coverage_start && summary.coverage_end ? `Coverage ${safeText(summary.coverage_start)} to ${safeText(summary.coverage_end)} · ${safeText(summary.school_day_count ?? '—')} instructional days` : 'Coverage details are not available from this local check.';
    const step = (number, title, description, stateText, action, view, completed = false) => `<article class="content-panel"><p class="eyebrow">STEP ${number} · ${safeText(stateText)}</p><h2>${safeText(title)}</h2><p>${safeText(description)}</p><button class="button ${completed ? 'secondary' : 'primary'}" type="button" data-setup-action="${safeText(action)}" data-go="${safeText(view)}">${safeText(action)}</button></article>`;
    const signInStep = `<article class="content-panel"><p class="eyebrow">STEP 3 · NOT YET VERIFIED</p><h2>Sign in to your school account</h2><p>Open the dedicated Edge profile for a saved form, then sign in manually. Opening Edge is not proof of sign-in; FormFiller checks when the runner opens the form.</p>${forms.length && state.session.mode === 'private' ? `<label class="field-label" for="signin-form">Form to open</label><select id="signin-form" class="answer-select">${forms.map(form=>`<option value="${safeText(form.id)}">${safeText(form.name || 'Saved form')}</option>`).join('')}</select><button type="button" id="open-sign-in" class="button primary">Open dedicated Edge sign-in</button>` : !forms.length ? '<p>Add and save a form first. Sign-in remains unverified until the runner opens a form.</p><button type="button" class="button secondary" data-go="forms">Add your first form</button>' : '<p>Manual sign-in is available from the private local workspace. This synthetic demo cannot open a school sign-in session.</p>'}</article>`;
    root.innerHTML = `<div class="page-heading"><div><h1>Setup</h1><p>Your progress is recalculated from the private workspace and current readiness checks. You can leave and return here anytime.</p></div><button class="button secondary" data-go="guide">Quick-start guide</button></div><div class="today-meta"><span><b>Forms</b> ${forms.length} configured</span><span><b>Reviewed</b> ${reviewedCount} of ${forms.length}</span><span><b>Calendar</b> ${calendarReady ? 'Validated' : 'Needs attention'}</span></div><div class="notice-box">Setup never submits a response. Only approved instructional dates permit a run, and the local runner tracks duplicates. Sign-in is checked when the runner opens a form.</div><div class="row-list">${step(1, 'Choose your private folder', 'Settings and saved responses live in this folder. Sign-in, locks, and submission tracking stay on this computer. The folder path is kept out of this screen.', workspaceReady ? 'Ready' : 'Needs attention', workspaceReady ? 'Folder selected' : 'Choose folder', 'setup', workspaceReady)}${step(2, 'Set up your school calendar', `A reviewed district calendar is required before Forms opens. ${calendarMeta} Missing, changed, stale, or uncovered dates remain blocked. Selecting a file does not approve it.`, calendarReady ? (calendar.code === 'non_school_day' ? 'Ready · today is a non-school day' : 'Ready') : 'Needs attention', 'Read calendar guide', 'guide', calendarReady)}${signInStep}${step(4, 'Add and review forms', 'Inspect each form, enter its template responses, save, then explicitly review the saved answers. Editing them requires another review.', forms.length === 0 ? 'Not started' : formReady ? 'Reviewed and ready' : `${reviewedCount} of ${forms.length} reviewed`, forms.length ? 'Open Forms' : 'Add your first form', forms.length ? 'forms' : 'forms', formReady)}${step(5, 'Review readiness', 'See current requirements and next actions. Live use requires a separate reviewed configuration action; completing this checklist never enables it.', readyData.ready ? 'Checks ready' : 'Needs attention', 'Review readiness', 'readiness', readyData.ready)}</div><div class="content-panel" id="setup-summary"><h2>Setup summary</h2><p>${forms.length} form${forms.length === 1 ? '' : 's'} configured; ${reviewedCount} reviewed. Calendar: ${calendarReady ? 'validated' : 'needs attention'}. Dedicated Edge sign-in: not yet verified. Live use: requires its separate reviewed configuration process.</p><button class="button primary" data-go="forms">Return to Forms</button></div>`;
    const calendarCoverage = summary.coverage_start && summary.coverage_end
      ? `Coverage ${summary.coverage_start} to ${summary.coverage_end} · ${summary.school_day_count ?? '—'} instructional days`
      : 'Coverage details are not available from this local check.';
    root.querySelector('#setup-summary > p').textContent = `${forms.length} form${forms.length === 1 ? '' : 's'} configured; ${reviewedCount} reviewed. Calendar: ${calendarCoverage}${calendarReady ? '' : ' · needs attention'}. Dedicated Edge sign-in: not yet verified. Live use: requires its separate reviewed configuration process.`;
    const unresolved = checks.filter(item => item.status === 'blocked' || item.status === 'unknown');
    if (unresolved.length) {
      const heading = document.createElement('h3');
      heading.textContent = 'Still needs attention';
      const list = document.createElement('ul');
      unresolved.forEach(item => {
        const row = document.createElement('li');
        row.textContent = `${item.label || 'Requirement'}: ${readinessCopy(item)[0]}`;
        list.append(row);
      });
      const button = root.querySelector('#setup-summary > button');
      root.querySelector('#setup-summary').insertBefore(heading, button);
      root.querySelector('#setup-summary').insertBefore(list, button);
    }
    root.querySelectorAll('[data-go]').forEach(button => button.addEventListener('click', async () => {
      if (button.dataset.setupAction === 'Choose folder' && !workspaceReady) { renderWorkspaceSetup(); return; }
      if (button.dataset.setupAction === 'Add your first form') { navigateView('forms'); setTimeout(() => openCreate(), 0); return; }
      navigateView(button.dataset.go);
    }));
    root.querySelector('#open-sign-in')?.addEventListener('click', async event => {
      const button=event.currentTarget;
      buttonBusy(button,true,'Opening Edge…');
      try { await request('/api/sign-in',{method:'POST',body:{form_id:root.querySelector('#signin-form').value}}); showNotice('The dedicated Edge profile opened. Sign in manually; this does not verify authentication.','info'); }
      catch (_) { showNotice('The sign-in window could not be opened. Check local readiness and try again.','error'); }
      finally { button.disabled=false; button.textContent='Open dedicated Edge sign-in'; }
    });
  };
  const renderGuide = () => {
    root.innerHTML = `<div class="page-heading"><div><h1>Teacher Guide</h1><p>Use FormFiller on this computer. No AI account or agent is needed.</p></div><button class="button secondary" data-go="setup">Back to setup</button></div><div class="content-panel"><h2>Before you begin</h2><p>Use the approved installed FormFiller application on the designated Windows computer. Keep the computer signed in for scheduled local runs. Your private folder contains settings and saved responses; authentication and submission tracking stay on this computer.</p><h2>1. Open FormFiller and choose a folder</h2><p>Launch the local application, then choose the private workspace folder when prompted. Returning users land on Forms; Setup is always available in the side menu.</p><h2>2. Review the school calendar</h2><p>Only dates in the reviewed district calendar can be used. Missing, changed, stale, or out-of-coverage dates stop a run before Forms opens. This screen cannot import or approve a calendar yet. Ask the person who manages your FormFiller installation to review the district SchoolDays source and install the reviewed calendar. Do not edit calendar files or approval dates yourself; selecting a file alone would not approve it.</p><h2>3. Add template responses</h2><p>In Forms, select Add form, enter a name and URL, inspect its questions, fill in the template responses, and save. Each form has its own responses. These answers are reused each time this form runs. Date fields use the run date. Then explicitly review saved answers. Editing them makes review necessary again. Unsupported question types stay unresolved; do not guess an answer.</p><h2>4. Check readiness and sign in</h2><p>Open Readiness to see current requirements and safe next steps. Sign in manually in the dedicated Edge profile. FormFiller does not infer success from opening Edge; sign-in is checked when the runner opens the form. Live mode requires a separate reviewed configuration process.</p><h2>5. Daily use and troubleshooting</h2><p>Use Today to review the date and form statuses. A run is allowed only when local checks pass, on an approved instructional date. The runner tracks duplicates; an uncertain result needs review and must not be resubmitted automatically. A non-school-day skip is normal.</p><h2>Attendance Preview</h2><p>The preview uses synthetic or local roster data. A J in a neighboring period suggests an absence; review every mark. Sending is unavailable in the private app until posting is verified.</p><h2>Installation</h2><p>Installation requires the approved local package, a dedicated Edge profile, and the designated local runtime. Everyday use requires launching that installed app and keeping this computer available. Contact the local installer for missing prerequisites; do not edit configuration files to bypass a blocker.</p></div>`;
    root.querySelectorAll('[data-go]').forEach(button => button.addEventListener('click', () => navigateView(button.dataset.go)));
  };
  const loadSkyward = async () => renderSkyward(await request('/api/skyward/config'));
  const renderSkyward = data => {
    state.skyward = data;
    state.skywardCourses = Array.isArray(data.config?.courses) ? data.config.courses.map(course => ({id:course.id || '', name:course.name || '', period:course.period || ''})) : [];
    const editable = Boolean(data.editable) && data.mode !== 'demo';
    root.innerHTML = `<div class="page-heading"><div><h1>Skyward settings</h1><p>Configure the district login URL and class identifiers. Sign-in stays manual in the dedicated Edge profile.</p></div><span class="tag ${editable ? 'good' : 'warn'}">${editable ? 'Editable' : 'Read only'}</span></div>${!editable ? `<div class="notice-box">Settings cannot be changed in ${safeText(data.mode || 'this')} mode. Any classes shown here are synthetic preview data.</div>` : ''}<div class="content-panel"><label class="field-label" for="skyward-login-url">District login URL <span class="required-mark">*</span></label><input id="skyward-login-url" type="url" required value="${safeText(data.config?.login_url || '')}" ${editable ? '' : 'disabled'} placeholder="https://district.example.edu"><p class="helper-text">Required. Use the URL supplied by your district. FormFiller cannot determine a class ID from this URL.</p><h2>Classes</h2><div id="skyward-course-list">${state.skywardCourses.map((course,index) => skywardCourseRow(course,index,editable)).join('') || '<p class="muted">No classes configured.</p>'}</div>${editable ? '<button type="button" class="button secondary" id="add-skyward-course">Add class</button><div class="editor-actions"><span id="skyward-save-status" class="editor-save-status" aria-live="polite"></span><button type="button" class="button primary" id="save-skyward">Save settings</button></div>' : ''}</div><div class="content-panel"><h2>Finding the class ID</h2><ol><li>Sign in to your district Skyward site manually in the dedicated Edge profile.</li><li>Open the class roster and its class details or roster settings.</li><li>Use the class identifier provided by the district page or administrator; enter the class name and optional period so you can recognize it here.</li><li>Do not guess an identifier from the login address. Ask your district administrator if it is not shown.</li></ol><figure class="notice-box"><figcaption>Fictional example · class details</figcaption><div aria-hidden="true">📖 Class: Algebra I　→　Period: 2　→　Class ID: 12345</div><p>This example is synthetic. Use the identifier shown by your district.</p></figure><p>Skyward is labeled Preview until reading and posting are verified. Review every attendance mark.</p></div>`;
    if (!editable) return;
    const collect = () => [...root.querySelectorAll('.skyward-course')].map(row => ({id:row.querySelector('[data-course-field="id"]').value.trim(),name:row.querySelector('[data-course-field="name"]').value.trim(),period:row.querySelector('[data-course-field="period"]').value.trim()}));
    root.querySelector('#add-skyward-course')?.addEventListener('click', () => { state.skywardCourses=collect(); state.skywardCourses.push({id:'',name:'',period:''}); root.querySelector('#skyward-course-list').innerHTML = state.skywardCourses.map((course,index)=>skywardCourseRow(course,index,true)).join(''); wireRemove(); });
    const wireRemove = () => root.querySelectorAll('[data-remove-course]').forEach(button => button.addEventListener('click', () => { state.skywardCourses=collect(); state.skywardCourses.splice(Number(button.dataset.removeCourse),1); root.querySelector('#skyward-course-list').innerHTML=state.skywardCourses.map((course,index)=>skywardCourseRow(course,index,true)).join('') || '<p class="muted">No classes configured.</p>'; wireRemove(); }));
    wireRemove();
    root.querySelector('#save-skyward')?.addEventListener('click', async event => { const button=event.currentTarget; const loginUrl=root.querySelector('#skyward-login-url').value.trim(); const courses=collect(); if (!loginUrl || !courses.length || courses.some(course => !course.name || !/^\d{3,12}$/.test(course.id))) { showNotice('Enter the district login URL and at least one class with a name and 3–12 digit class ID.', 'error'); return; } buttonBusy(button,true,'Saving…'); try { const result=await request('/api/skyward/config',{method:'PUT',body:{login_url:loginUrl,courses}}); renderSkyward(result); showNotice('Skyward settings saved in the private workspace.','success'); } catch(error) { showNotice(error.code === 'demo_config_read_only' ? 'Settings are read-only in this mode.' : 'Settings could not be saved. Check the URL and required class fields.', 'error'); button.disabled=false; button.textContent='Save settings'; } });
  };
  const skywardCourseRow = (course,index,editable) => `<div class="skyward-course"><label class="field-label">Class name <span class="required-mark">*</span><input type="text" data-course-field="name" required maxlength="120" value="${safeText(course.name)}" ${editable ? '' : 'disabled'}></label><label class="field-label">Class ID <span class="required-mark">*</span><input type="text" data-course-field="id" required inputmode="numeric" pattern="[0-9]{3,12}" minlength="3" maxlength="12" value="${safeText(course.id)}" ${editable ? '' : 'disabled'}></label><label class="field-label">Period (optional)<input type="text" data-course-field="period" maxlength="40" value="${safeText(course.period)}" ${editable ? '' : 'disabled'}></label>${editable ? `<button type="button" class="text-action remove" data-remove-course="${index}">Remove class</button>` : ''}</div>`;
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
        if (!session.needs_setup) { state.view='forms'; nav.querySelectorAll('.nav-item').forEach(item => item.classList.toggle('active', item.dataset.view === 'forms')); document.querySelector('#crumb-current').textContent='Forms'; await loadForms(); if (!state.forms.length) navigateView('setup'); showNotice(`${displayName} selected.`, 'success'); }
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
      if (session.needs_setup) renderWorkspaceSetup(); else { const data=await request('/api/forms'); state.forms=Array.isArray(data.forms)?data.forms:[]; state.selectedId=state.forms[0]?.id || null; if (!state.forms.length) navigateView('setup'); else renderForms(); }
    } catch(error) {
      showNotice(error.message || 'The local FormFiller service could not be reached.','error');
      root.innerHTML='<div class="empty-state"><div class="empty-icon" aria-hidden="true">!</div><h2>Unable to load workspace</h2><p>Check that the local FormFiller service is running, then refresh.</p><button class="button secondary" id="try-again">Try again</button></div>';
      root.querySelector('#try-again').addEventListener('click', () => location.reload());
    }
  });
})();
