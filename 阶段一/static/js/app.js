'use strict';
const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const page = document.body.dataset.page;
const surveyId = document.body.dataset.surveyId;
const types = {single_choice:'单选题',multiple_choice:'多选题',text:'文本填空',number:'数字填空'};
const statuses = {draft:'草稿',published:'收集中',closed:'已关闭'};
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const date = value => value ? new Date(value).toLocaleString('zh-CN', {hour12:false}) : '不限';
let noticeTimer;
function notice(message, error = false) {
  const el = $('#notice'); el.textContent = message; el.classList.toggle('error',error); el.hidden = false;
  clearTimeout(noticeTimer); noticeTimer = setTimeout(() => {el.hidden = true;}, error ? 9000 : 4500);
}
async function api(path, method='GET', body) {
  let response;
  try { response = await fetch(path,{method,credentials:'same-origin',headers:body===undefined?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)}); }
  catch {throw new Error('无法连接服务器，请检查连接后重试。');}
  const data = await response.json().catch(() => ({error:'服务器返回了无法读取的结果'}));
  if (!response.ok) {
    if(response.status === 401 && !['login','register'].includes(page)) location.href = '/login?next='+encodeURIComponent(location.pathname);
    const error = new Error(data.error || '操作失败'); error.data=data; error.status=response.status; throw error;
  }
  return data;
}
function action(el, event, fn) {
  if(!el) return;
  el.addEventListener(event, async e => {
    e.preventDefault(); const button = event==='submit' ? $('button[type="submit"]', el) : el;
    if(button?.disabled) return;
    if(button) button.disabled=true;
    try {await fn(e);} catch(error) {notice(error.message,true);} finally {if(button) button.disabled=false;}
  });
}
function confirmAction(message) {
  const dialog=$('#confirm-dialog'); $('#confirm-text').textContent=message; dialog.returnValue='cancel'; dialog.showModal();
  return new Promise(resolve=>dialog.addEventListener('close',()=>resolve(dialog.returnValue==='confirm'),{once:true}));
}
const empty = (title,body) => `<div class="empty-state"><div class="empty-mark">▤</div><h2>${esc(title)}</h2><p class="muted">${esc(body)}</p></div>`;
async function authPage() {
  const form=$('#auth-form');
  action(form,'submit',async()=>{
    const body={username:form.elements.username.value,password:form.elements.password.value};
    if(page==='register') await api('/api/register','POST',body);
    await api('/api/login','POST',body);
    location.href=form.dataset.next || '/dashboard';
  });
}
async function account() {
  const data=await api('/api/me'); $('#account-name').textContent=data.user.username;
  action($('#logout'),'click',async()=>{await api('/api/logout','POST');location.href='/login';});
}
async function dashboard() {
  let surveys=(await api('/api/surveys')).surveys, filter='all';
  $('#count-all').textContent=surveys.length;
  $('#count-published').textContent=surveys.filter(s=>s.status==='published'&&(!s.deadline||new Date(s.deadline)>new Date())).length;
  $('#count-draft').textContent=surveys.filter(s=>s.status==='draft').length;
  function render() {
    const list=surveys.filter(s=>(filter==='all'||s.status===filter)&&s.title.toLowerCase().includes($('#search').value.toLowerCase()));
    $('#survey-list').innerHTML=list.length?list.map(s=>{
      const expired=s.status==='published'&&s.deadline&&new Date(s.deadline)<=new Date();
      return `<article class="survey-card"><div class="card-top"><span class="survey-symbol" aria-hidden="true">▤</span><span class="badge ${expired?'expired':esc(s.status)}">${expired?'已截止':statuses[s.status]}</span></div><h3>${esc(s.title)}</h3><p class="description">${esc(s.description||'尚未添加问卷说明')}</p><div class="card-meta"><span>${s.questionCount} 道题目</span><span>${esc(new Date(s.createdAt).toLocaleDateString('zh-CN'))} 创建</span></div><div class="card-footer"><a href="/surveys/${esc(s.id)}/edit">${s.status==='draft'?'继续编辑':'查看配置'} ↗</a><a href="/surveys/${esc(s.id)}/statistics">查看统计</a>${s.status==='published'?`<a class="right" href="/survey/${esc(s.id)}">填写 ↗</a>`:''}</div></article>`;
    }).join(''):empty(surveys.length?'没有找到符合条件的问卷':'把你的第一个问题，交给世界',surveys.length?'试试其他标题或状态。':'点击右上角「创建问卷」，开始收集反馈。');
  }
  $$('.tab').forEach(tab=>tab.addEventListener('click',()=>{$$('.tab').forEach(t=>t.classList.toggle('active',t===tab));filter=tab.dataset.filter;render();}));
  $('#search').addEventListener('input',render);render();
}
async function editor() {
  let survey=null, editing=null, ruleSource=null;
  const base=surveyId?'/api/surveys/'+surveyId:null;
  const form=$('#survey-form'), qform=$('#question-form'), rform=$('#rule-form');
  function settings(){return {title:form.elements.title.value,description:form.elements.description.value,anonymousAllowed:form.elements.anonymousAllowed.checked,allowMultipleResponses:form.elements.allowMultipleResponses.checked};}
  async function load() {
    survey=(await api(base+'/manage')).survey;
    $('#editor-heading').textContent=survey.title;
    form.elements.title.value=survey.title; form.elements.description.value=survey.description;
    form.elements.anonymousAllowed.checked=survey.anonymousAllowed;
    form.elements.allowMultipleResponses.checked=survey.allowMultipleResponses;
    [...form.elements].forEach(el=>el.disabled=!survey.canEdit);
    $('#save-settings').hidden=!survey.canEdit;
    $('#survey-actions').hidden=false; $('#stats-link').href=`/surveys/${surveyId}/statistics`;
    $('#publish').hidden=!survey.canEdit;
    $('#questions-panel').hidden=false; $('#question-count').textContent=survey.questions.length+' 道题';
    $('#editor-status').textContent=statuses[survey.status];$('#editor-status').className='badge '+survey.status;
    $('#add-question').hidden=!survey.canEdit;
    $('#share-box').hidden=survey.status==='draft';$('#draft-note').hidden=survey.status!=='draft';
    $('#deadline-panel').hidden=survey.status!=='published';
    $('#share-url').value=location.origin+'/survey/'+surveyId;$('#fill-link').href='/survey/'+surveyId;
    if(survey.deadline){const d=new Date(survey.deadline);$('#deadline-input').value=new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,16);}else $('#deadline-input').value='';
    $('#question-list').innerHTML=survey.questions.length?survey.questions.map(q=>`<article class="question-item"><div class="type">${types[q.type]} · 第 ${q.order} 题</div><h3>${esc(q.title)}${q.required?'<span class="required-mark">必答</span>':''}</h3>${q.options.length?`<div class="question-options">${q.options.map(o=>`<div>${q.type==='single_choice'?'○':'□'} ${esc(o.label)}</div>`).join('')}</div>`:''}<p class="hint">${esc(validationHint(q))}</p>${q.jumpRules.map((r,i)=>`<div class="rule-item"><span>${esc(ruleLabel(q,r))}</span>${survey.canEdit?`<button data-remove-rule="${q.id}" data-rule-index="${i}" type="button" aria-label="删除跳转规则">删除</button>`:''}</div>`).join('')}${survey.canEdit?`<div class="question-tools"><button class="button secondary small" data-edit="${q.id}">编辑</button>${q.type!=='text'&&q.order<survey.questions.length?`<button class="button secondary small" data-rule="${q.id}">设置跳转</button>`:''}<button class="button secondary small" data-delete="${q.id}">删除题目</button></div>`:''}</article>`).join(''):'<p class="muted">还没有题目。先添加一道题，让问卷有个开始。</p>';
  }
  function ruleLabel(q,r){const names={equals:'等于',contains:'包含',gt:'大于',gte:'大于等于',lt:'小于',lte:'小于等于'}; const target=survey.questions.find(t=>t.id===r.targetQuestionId);const value=q.options.find(o=>o.value===r.condition.value)?.label??r.condition.value;return `当答案${names[r.condition.operator]}「${value}」→ 第 ${target?.order??'?'} 题`;}
  function toggleFields(){const type=qform.elements.type.value;$('#choice-fields').hidden=!['single_choice','multiple_choice'].includes(type);$('#multi-fields').hidden=type!=='multiple_choice';$('#text-fields').hidden=type!=='text';$('#number-fields').hidden=type!=='number';for(const id of ['#choice-fields','#multi-fields','#text-fields','#number-fields']){const group=$(id);$$('input,textarea',group).forEach(el=>el.disabled=group.hidden);}}
  function openQuestion(q=null){editing=q; qform.reset();$('#builder-title').textContent=q?'编辑题目':'添加题目';if(q){qform.elements.type.value=q.type;qform.elements.title.value=q.title;qform.elements.required.checked=q.required;qform.elements.options.value=q.options.map(o=>o.label).join('\n');for(const [key,value] of Object.entries(q.validation)){if(qform.elements[key]){if(key==='integerOnly')qform.elements[key].checked=value;else qform.elements[key].value=value??'';}}}toggleFields();$('#question-builder').hidden=false;$('#question-builder').scrollIntoView({behavior:'smooth',block:'center'});}
  qform.elements.type.addEventListener('change',toggleFields);
  action(form,'submit',async()=>{if(!base){const data=await api('/api/surveys','POST',settings());location.href='/surveys/'+data.survey.id+'/edit';}else{await api(base,'PATCH',settings());await load();notice('基本信息已保存');}});
  action($('#add-question'),'click',()=>openQuestion());
  action($('#cancel-question'),'click',()=>{$('#question-builder').hidden=true;});
  action(qform,'submit',async()=>{
    const f=qform.elements,type=f.type.value;
    const payload={type,title:f.title.value,required:f.required.checked,validation:{}};
    const num=name=>f[name].value===''?null:Number(f[name].value);
    if(['single_choice','multiple_choice'].includes(type)) payload.options=f.options.value.split('\n').map(s=>s.trim()).filter(Boolean).map((label,i)=>({value:editing?.options[i]?.value??'option_'+crypto.randomUUID(),label}));
    if(type==='multiple_choice')payload.validation={minSelections:num('minSelections')??0,maxSelections:num('maxSelections')??payload.options.length};
    if(type==='text')payload.validation={minLength:num('minLength')??0,maxLength:num('maxLength')??1000};
    if(type==='number')payload.validation={min:num('min'),max:num('max'),integerOnly:f.integerOnly.checked};
    await api(base+'/questions'+(editing?'/'+editing.id:''),editing?'PUT':'POST',payload);$('#question-builder').hidden=true;await load();notice('题目已保存');
  });
  $('#question-list').addEventListener('click',async e=>{
    const b=e.target.closest('button');if(!b||b.disabled)return;b.disabled=true;
    try{
      if(b.dataset.edit) openQuestion(survey.questions.find(q=>q.id===b.dataset.edit));
      if(b.dataset.delete&&await confirmAction('删除这道题？指向它的跳转规则需要先删除。')){await api(base+'/questions/'+b.dataset.delete,'DELETE');await load();notice('题目已删除');}
      if(b.dataset.removeRule){await api(base+'/questions/'+b.dataset.removeRule+'/rules/'+b.dataset.ruleIndex,'DELETE');await load();notice('规则已删除');}
      if(b.dataset.rule){ruleSource=survey.questions.find(q=>q.id===b.dataset.rule);const isNumber=ruleSource.type==='number';rform.elements.operator.innerHTML=(isNumber?[['equals','等于'],['gt','大于'],['gte','大于等于'],['lt','小于'],['lte','小于等于']]:[[ruleSource.type==='single_choice'?'equals':'contains',ruleSource.type==='single_choice'?'等于':'包含']]).map(([v,l])=>`<option value="${v}">${l}</option>`).join('');rform.elements.choice.hidden=isNumber;rform.elements.number.hidden=!isNumber;rform.elements.number.required=isNumber;rform.elements.number.value='';rform.elements.choice.innerHTML=ruleSource.options.map(o=>`<option value="${esc(o.value)}">${esc(o.label)}</option>`).join('');rform.elements.target.innerHTML=survey.questions.filter(q=>q.order>ruleSource.order).map(q=>`<option value="${q.id}">第 ${q.order} 题 · ${esc(q.title)}</option>`).join('');$('#rule-dialog').showModal();}
    }catch(error){notice(error.message,true);}finally{b.disabled=false;}
  });
  action($('#cancel-rule'),'click',()=>$('#rule-dialog').close());
  action(rform,'submit',async()=>{await api(base+'/questions/'+ruleSource.id+'/rules','POST',{operator:rform.elements.operator.value,value:ruleSource.type==='number'?Number(rform.elements.number.value):rform.elements.choice.value,targetQuestionId:rform.elements.target.value});$('#rule-dialog').close();await load();notice('跳转规则已保存');});
  action($('#publish'),'click',async()=>{if(!await confirmAction('发布后题目和填写设置将锁定。确认发布这份问卷？'))return;await api(base,'PATCH',settings());await api(base+'/publish','POST');await load();notice('问卷已发布，可以分享填写链接了');});
  action($('#copy-link'),'click',async()=>{try{await navigator.clipboard.writeText($('#share-url').value);notice('链接已复制');}catch{$('#share-url').select();notice('请复制已选中的链接');}});
  action($('#save-deadline'),'click',async()=>{const value=$('#deadline-input').value;await api(base+'/deadline','PUT',{deadline:value?new Date(value).toISOString():null});await load();notice('截止时间已保存');});
  action($('#close-survey'),'click',async()=>{if(await confirmAction('关闭后将不再接收新回答。确认关闭问卷？')){await api(base+'/close','POST');await load();notice('问卷已关闭');}});
  if(base)await load();
}
function validationHint(q){const v=q.validation; if(q.type==='multiple_choice')return `选择 ${v.minSelections??0}–${v.maxSelections??q.options.length} 项${q.required?'':'，可跳过'}`;if(q.type==='text')return `${v.minLength??0}–${v.maxLength??1000} 个字符`;if(q.type==='number')return `${v.integerOnly?'整数':'数字'} · 最小 ${v.min??'不限'} · 最大 ${v.max??'不限'}`;return '请选择一个选项';}
async function filling() {
  const base='/api/surveys/'+surveyId;
  const survey=(await api(base)).survey;
  $('#fill-title').textContent=survey.title;$('#fill-description').textContent=survey.description;
  $('#fill-meta').textContent=`${survey.allowMultipleResponses?'允许多次填写':'每个账号限提交一次'} · 截止时间：${date(survey.deadline)}`;
  if(survey.alreadySubmitted){$('#fill-body').innerHTML=empty('你已提交过这份问卷','感谢参与。本问卷不允许重复填写。');return;}
  const answers={}, questions=new Map(survey.questions.map(q=>[q.id,q])); let current=null, visited=[];
  const form=$('#answer-form');
  function render(q,oldValue){current=q;$('#submit-box').hidden=true;form.hidden=false;$('#fill-body').innerHTML=`<div class="question-label">第 ${q.order} 题 · ${types[q.type]}${q.required?' · 必答':' · 可跳过'}</div><h2>${esc(q.title)}</h2><p class="hint">${esc(validationHint(q))}</p>`;$('#previous').disabled=visited.length===0;$('#question-error').textContent='';
    let html='';if(['single_choice','multiple_choice'].includes(q.type))html=q.options.map(o=>`<label class="answer-option"><input type="${q.type==='single_choice'?'radio':'checkbox'}" name="value" value="${esc(o.value)}" ${(Array.isArray(oldValue)?oldValue.includes(o.value):oldValue===o.value)?'checked':''}><span>${esc(o.label)}</span></label>`).join('');
    else if(q.type==='text')html=`<label>你的回答<textarea name="value" rows="4" placeholder="请填写你的回答">${esc(oldValue??'')}</textarea></label>`;
    else html=`<label>你的回答<input name="value" type="number" step="${q.validation.integerOnly?'1':'any'}" ${q.validation.min!=null?`min="${q.validation.min}"`:''} ${q.validation.max!=null?`max="${q.validation.max}"`:''} value="${esc(oldValue??'')}" placeholder="请输入数字"></label>`;
    $('#answer-control').innerHTML=html;
  }
  async function next(){const result=await api(base+'/next','POST',{answers});visited=result.visitedQuestionIds;if(result.completed){current=null;form.hidden=true;$('#fill-body').innerHTML='<div class="question-label">即将完成</div>';$('#submit-box').hidden=false;$('#anonymous-label').hidden=!survey.anonymousAllowed;}else render(result.nextQuestion);}
  function previous(){if(!visited.length)return;if(current)delete answers[current.id];const id=visited[visited.length-1],value=answers[id];delete answers[id];visited=visited.slice(0,-1);render(questions.get(id),value);}
  form.addEventListener('submit',async e=>{e.preventDefault();const b=$('#answer-next');if(b.disabled)return;b.disabled=true;$('#question-error').textContent='';try{let value;if(current.type==='multiple_choice')value=$$('input:checked',form).map(i=>i.value);else if(current.type==='single_choice')value=$('input:checked',form)?.value??null;else{const raw=form.elements.value.value;value=raw===''?null:current.type==='number'?Number(raw):raw;}answers[current.id]=value;await next();}catch(error){$('#question-error').textContent=error.message;}finally{b.disabled=false;}});
  action($('#previous'),'click',previous);action($('#review-answer'),'click',previous);
  action($('#submit-response'),'click',async()=>{const result=await api(base+'/responses','POST',{answers,anonymous:$('#anonymous').checked});$('#submit-box').hidden=true;$('#fill-body').innerHTML=`<div class="success-state"><div class="success-icon">✓</div><h2>感谢，你的回答已收到。</h2><p class="muted">${result.recovered?'已恢复并保存首次提交的回答。':'每一份认真填写，都让结果更有价值。'}</p>${survey.allowMultipleResponses?'<button class="button secondary" id="fill-again">再次填写</button>':'<a class="button secondary" href="/dashboard">返回我的问卷</a>'}</div>`;action($('#fill-again'),'click',()=>location.reload());});
  await next();
}
async function statistics() {
  const base='/api/surveys/'+surveyId;
  $('#back-editor').href='/surveys/'+surveyId+'/edit';let results=[];
  function render(){const id=$('#question-filter').value;$('#stats-scope').textContent=id==='all'?'全部题目':'单道题目';$('#statistics-list').innerHTML=results.filter(q=>id==='all'||q.questionId===id).map((q)=>`<section class="panel stat-panel"><div class="stat-question"><div><span class="eyebrow">${types[q.type]}</span><h2>${esc(q.title)}</h2></div><span class="muted">${q.answeredCount} 次回答</span></div>${q.optionCounts?q.optionCounts.map(o=>`<div class="bar-row"><div class="bar-label"><span>${esc(o.label)}</span><span>${o.count} 次 · ${q.answeredCount?Math.round(o.count/q.answeredCount*100):0}%</span></div><div class="bar-track"><div class="bar-fill" style="width:${q.answeredCount?Math.min(100,o.count/q.answeredCount*100):0}%"></div></div></div>`).join(''):q.type==='number'?`<div class="average">${q.average==null?'—':Number(q.average.toFixed(2))}<small>平均值</small></div><ul class="stat-values">${q.numericAnswers.map(v=>`<li>${esc(v)}</li>`).join('')||'<li class="muted">暂无回答</li>'}</ul>`:`<ul class="stat-values">${q.answers.map(v=>`<li>${esc(v)}</li>`).join('')||'<li class="muted">暂无回答</li>'}</ul>`}</section>`).join('')||empty('还没有题目','添加题目并发布后，统计结果会显示在这里。');}
  async function load(){const selected=$('#question-filter').value;const data=await api(base+'/statistics');results=data.questions;$('#stats-title').textContent=data.title;$('#response-count').textContent=data.responseCount;$('#stats-question-count').textContent=results.length;$('#stats-time').textContent='更新于 '+new Date().toLocaleTimeString('zh-CN');$('#question-filter').innerHTML='<option value="all">全部题目</option>'+results.map((q,i)=>`<option value="${q.questionId}">第 ${i+1} 题 · ${esc(q.title)}</option>`).join('');if(selected==='all'||results.some(q=>q.questionId===selected))$('#question-filter').value=selected;render();}
  $('#question-filter').addEventListener('change',render);action($('#refresh-stats'),'click',load);await load();
}
(async()=>{try{if(['login','register'].includes(page)){await authPage();return;}await account();await ({dashboard,editor,fill:filling,statistics}[page]?.());}catch(error){notice(error.message,true);const target=page==='fill'?$('#fill-body'):page==='dashboard'?$('#survey-list'):null;if(target)target.innerHTML=empty('暂时无法打开',error.message);}})();
