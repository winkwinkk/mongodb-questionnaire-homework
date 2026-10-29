'use strict';
// Second-stage pages reuse the existing authenticated API, notices and visual language.
window.Stage2 = (() => {
  const qid = document.body.dataset.questionId;
  const questionBase = id => '/api/questions/' + encodeURIComponent(id);
  const metricNames = {choiceDistribution:'选项分布',numericMean:'数字平均值',numericDistribution:'数字分布',textResponses:'文本回答数量'};
  const fields = {title:'题干',type:'题型',required:'默认必答',options:'选项',validation:'校验范围',unit:'单位',semanticDescription:'统计语义'};
  const number = n => n == null ? '—' : Number(n).toLocaleString('zh-CN', {maximumFractionDigits:4});
  const link = (id, label='查看题目') => `<a class="text-link" href="/questions/${esc(id)}">${esc(label)} ↗</a>`;
  const button = (label, attrs='', style='secondary') => `<button type="button" class="button ${style} small" ${attrs}>${label}</button>`;
  const options = (rows, value, label) => rows.map(row => `<option value="${esc(value(row))}">${esc(label(row))}</option>`).join('');
  const bind = (selector, fn, event='click') => action(typeof selector==='string'?$(selector):selector,event,fn);
  function delegate(root, fn) {
    root.addEventListener('click', async event => {
      const target=event.target.closest('button'); if(!target || target.disabled) return;
      target.disabled=true;
      try {await fn(target);} catch(error) {notice(error.message,true);} finally {target.disabled=false;}
    });
  }
  async function all(path, key) {
    let rows=[], cursor, seen=new Set();
    do {
      const data=await api(path+(path.includes('?')?'&':'?')+'limit=100'+(cursor?'&before='+encodeURIComponent(cursor):''));
      rows.push(...data[key]); cursor=data.hasMore?data.nextBefore:null;
      if(cursor && seen.has(cursor)) throw new Error('分页状态异常，请刷新后重试');
      seen.add(cursor);
    } while(cursor);
    return rows;
  }
  function closeButtons(root=document) {$$('[data-close-dialog]',root).forEach(b=>bind(b,()=>b.closest('dialog').close()));}
  const pendingKey = () => 'wenxu:pending:'+currentUser.id;
  function pending() {try{return JSON.parse(sessionStorage.getItem(pendingKey())||'{}');}catch{return {};}}
  function storePending(rows) {sessionStorage.setItem(pendingKey(),JSON.stringify(rows)); renderPending();}
  function renderPending() {
    const root=$('#pending-operations'); if(!root || !currentUser) return;
    const rows=Object.entries(pending()); root.hidden=!rows.length;
    root.innerHTML=rows.map(([key,p],index)=>`<div><strong>有一项操作结果尚未确认：${esc(p.label)}</strong><p>重试会发送首次内容。移除提醒不会撤销服务器可能已保存的结果。</p>${button('重试首次操作',`data-retry-pending="${index}"`)} ${button('移除提醒',`data-forget-pending="${index}"`)}</div>`).join('');
    $$('button',root).forEach(b=>bind(b,async()=>{
      const index=Number(b.dataset.retryPending??b.dataset.forgetPending), [key,p]=rows[index];
      if(b.dataset.forgetPending!==undefined){if(!await confirmAction('先核对已有结果。移除这条提醒不会撤销服务器已接受的操作，确认移除？'))return;}
      else {
        try {const result=await api(p.path,p.method,p.body);notice(result.message||'首次操作已确认');}
        catch(error){if(!error.status||error.status>=500)throw error;const data=pending();delete data[key];storePending(data);throw error;}
      }
      const data=pending();delete data[key];storePending(data);location.reload();
    }));
  }
  async function durable(key, label, path, method, payload) {
    const rows=pending();
    if(rows[key]) throw new Error('此操作有未确认结果，请先在页面顶部重试首次操作或核对后移除提醒。');
    const body={...payload,operationId:crypto.randomUUID()};
    rows[key]={label,path,method,body};storePending(rows);
    try {const result=await api(path,method,body);const latest=pending();delete latest[key];storePending(latest);return result;}
    catch(error){if(error.status && error.status<500){const latest=pending();delete latest[key];storePending(latest);}throw error;}
  }
  async function addSnapshot(path, payload) {
    try{return await api(path,'POST',payload);}catch(error){
      if(!error.status||error.status>=500)throw new Error('选题结果尚未确认。请刷新目标问卷核对，避免重复加入。');
      throw error;
    }
  }
  function modal(title, content, submitLabel, submit) {
    const dialog=document.createElement('dialog');dialog.className='large-dialog';
    dialog.innerHTML=`<form><h2>${esc(title)}</h2>${content}<div class="actions"><button class="button" type="submit">${esc(submitLabel)}</button><button class="button secondary" type="button" data-close-dialog>取消</button></div></form>`;
    document.body.append(dialog);closeButtons(dialog);dialog.addEventListener('close',()=>dialog.remove(),{once:true});
    bind($('form',dialog),async()=>{await submit($('form',dialog),dialog);},'submit');dialog.showModal();return dialog;
  }
  function contentEditor(form) {
    const f=form.elements, root=$('.option-editor',form);
    function row(option={value:'option_'+crypto.randomUUID(),label:''}) {
      const div=document.createElement('div');div.className='option-row';div.dataset.value=option.value;
      div.innerHTML=`<input aria-label="选项文字" maxlength="200" value="${esc(option.label)}" required>${button('移除','data-remove-option')}`;
      $('button',div).addEventListener('click',()=>div.remove());root.append(div);
    }
    function toggle() {
      $$('[data-fields]',form).forEach(group=>{group.hidden=group.dataset.fields==='choices'?!['single_choice','multiple_choice'].includes(f.type.value):group.dataset.fields!==f.type.value;
        $$('input,button',group).forEach(el=>el.disabled=group.hidden);});
    }
    f.type.addEventListener('change',toggle);bind($('[data-add-option]',form),()=>row());
    function fill(content={type:'single_choice',required:true,options:[{value:'option_'+crypto.randomUUID(),label:''},{value:'option_'+crypto.randomUUID(),label:''}]}) {
      form.reset();root.replaceChildren();f.type.value=content.type;f.questionTitle.value=content.title||'';f.required.checked=content.required??true;
      f.unit.value=content.unit||'';f.semanticDescription.value=content.semanticDescription||'';
      (content.options||[]).forEach(row);
      for(const [key,value] of Object.entries(content.validation||{}))if(f[key]){if(f[key].type==='checkbox')f[key].checked=value;else f[key].value=value??'';}
      toggle();
    }
    function read() {
      const type=f.type.value, numeric=name=>f[name].value===''?null:Number(f[name].value);
      const content={type,title:f.questionTitle.value,required:f.required.checked,unit:f.unit.value,semanticDescription:f.semanticDescription.value,validation:{}};
      if(['single_choice','multiple_choice'].includes(type))content.options=$$('.option-row',root).map(r=>({value:r.dataset.value,label:$('input',r).value}));
      if(type==='multiple_choice')content.validation={minSelections:numeric('minSelections')??0,maxSelections:numeric('maxSelections')??content.options.length};
      if(type==='text')content.validation={minLength:numeric('minLength')??0,maxLength:numeric('maxLength')??1000};
      if(type==='number')content.validation={min:numeric('min'),max:numeric('max'),integerOnly:f.integerOnly.checked};
      return content;
    }
    fill();return {fill,read};
  }
  function previewContent(version) {
    const c=version.content;
    return `<div class="version-content"><span class="eyebrow">${esc(types[c.type])} · v${version.versionNumber}</span><h3>${esc(c.title)}</h3><p class="hint">${c.required?'默认必答':'默认可跳过'}${c.unit?' · 单位：'+esc(c.unit):''}</p>${c.options?`<ol>${c.options.map(o=>`<li>${esc(o.label)}</li>`).join('')}</ol>`:''}<p class="muted">${esc(c.semanticDescription||'未填写统计语义')}</p><p class="hint">${esc(validationHint({...c,options:c.options||[],validation:c.validation||{}}))}</p></div>`;
  }
  async function versionsFor(id, extraId) {
    const detail=await api(questionBase(id));
    if(detail.question.ownerId===currentUser.id)return {question:detail.question,versions:await all(questionBase(id)+'/versions','versions')};
    const versions=[detail.version];
    if(extraId && extraId!==detail.version.id)versions.push((await api(questionBase(id)+'/versions/'+encodeURIComponent(extraId))).version);
    return {question:detail.question,versions};
  }
  async function library() {
    closeButtons();let tab='owned', rows=[], cursor=null;
    const form=$('#content-form'), editor=contentEditor(form);
    function render(){const search=$('#library-search').value.toLowerCase();const list=rows.filter(q=>(q.title||q.displayTitleSnapshot||'').toLowerCase().includes(search));
      $('#library-list').innerHTML=list.length?list.map(q=>{
        const question=tab==='owned'?q:q.question, id=question?.id||q.questionId;
        return `<article class="survey-card"><span class="badge">${tab==='owned'?'我的题目':'指定共享'}</span><h3>${esc(q.title||question?.title||q.displayTitleSnapshot)}</h3><p class="muted">${question?'推荐版本 v'+question.currentVersionNumber:'当前不可选用'}</p><div class="card-footer">${question?link(id,'查看与使用'):'<span>授权或题目状态已变化</span>'}<a href="/questions/${esc(id)}/statistics">使用与统计</a></div></article>`;
      }).join(''):empty('这里还没有题目',tab==='owned'?'新建题目，或在问卷编辑页将旧题保存到题目库。':'收到的有效指定共享会显示在这里。');
    }
    async function load(more=false){const data=await api(tab==='owned'?'/api/questions':'/api/shared-questions?limit=50'+(more&&cursor?'&before='+encodeURIComponent(cursor):''));rows=more?[...rows,...data.shares]:tab==='owned'?data.questions:data.shares;cursor=data.nextBefore;$('#library-more').hidden=!data.hasMore;render();}
    $$('[data-library-tab]').forEach(b=>bind(b,async()=>{tab=b.dataset.libraryTab;$$('[data-library-tab]').forEach(t=>{t.classList.toggle('active',t===b);t.setAttribute('aria-selected',String(t===b));});await load();}));
    $('#library-search').addEventListener('input',render);bind('#library-more',()=>load(true));
    bind('#create-question',()=>{editor.fill();$('#content-dialog').showModal();});
    bind(form,async()=>{const body={content:editor.read(),changeNote:form.elements.changeNote.value};if(form.elements.managementTitle.value.trim())body.title=form.elements.managementTitle.value.trim();const result=await durable('new-question','新建题目','/api/questions','POST',body);location.href='/questions/'+result.question.id;},'submit');
    await load();
  }
  async function question() {
    closeButtons();const base=questionBase(qid), form=$('#content-form'), editor=contentEditor(form);
    let detail, versions=[], selected, editBasis, shares=[], shareCursor;
    $('#question-stats-link').href='/questions/'+qid+'/statistics';
    function renderSelected(){selected=versions.find(v=>v.id===$('#version-select').value);$('#version-preview').innerHTML=previewContent(selected);$('#select-current').disabled=selected.id===detail.currentVersionId;}
    async function load(preferred){const data=await versionsFor(qid,new URLSearchParams(location.search).get('versionId'));detail=data.question;versions=data.versions;
      const owner=detail.ownerId===currentUser.id;
      $('#question-title').textContent=detail.title;$('#question-meta').textContent=(owner?'我的题目':'共享题目')+' · 推荐版本 v'+detail.currentVersionNumber+' · 已有问卷保持原快照';
      $('#current-version').textContent='推荐 v'+detail.currentVersionNumber;
      const old=preferred||$('#version-select').value||new URLSearchParams(location.search).get('versionId');$('#version-select').innerHTML=options(versions,v=>v.id,v=>'v'+v.versionNumber+' · '+v.content.title+(v.id===detail.currentVersionId?'（推荐）':''));if(versions.some(v=>v.id===old))$('#version-select').value=old;else $('#version-select').value=detail.currentVersionId;renderSelected();
      ['#new-version','#restore-version','#select-current','#history-panel','#sharing-panel'].forEach(id=>$(id).hidden=!owner);
      $('#question-workspace').hidden=false;
      $('#version-history').innerHTML=owner?versions.map(v=>`<div class="history-row"><strong>v${v.versionNumber}${v.id===detail.currentVersionId?' · 推荐':''}</strong><span>${esc(date(v.createdAt))}</span><p>${esc(v.changeNote||'初始内容')} ${v.creationOutcome==='branch'?'<span class="badge">保存为分支</span>':''}</p>${button('查看',`data-view-version="${v.id}"`)}</div>`).join(''):'';
      $('#versions-more').hidden=true;
      for(const name of ['from','to'])$('#diff-form').elements[name].innerHTML=options(versions,v=>v.id,v=>'v'+v.versionNumber+' · '+v.content.title);
      if(versions.length>1)$('#diff-form').elements.to.selectedIndex=1;
      if(owner)await loadShares();
    }
    async function loadShares(more=false){const data=await api(base+'/shares?limit=50'+(more&&shareCursor?'&before='+shareCursor:''));shares=more?[...shares,...data.shares]:data.shares;shareCursor=data.nextBefore;$('#shares-more').hidden=!data.hasMore;
      $('#share-history').innerHTML=shares.map(s=>`<div class="history-row"><strong>${s.status==='active'?'有效共享':'已撤销'}</strong><p>接收用户：${esc(s.recipientUsername||"用户已不存在")}</p><p class="hint">授权 ${esc(date(s.createdAt))}${s.revokedAt?' · 撤销 '+esc(date(s.revokedAt)):''}</p>${s.status==='active'?button('撤销共享',`data-revoke="${s.id}"`):button('重新授权',`data-regrant="${s.recipientUserId}"`)}</div>`).join('')||'<p class="muted">尚未共享给其他用户。</p>';
    }
    $('#version-select').addEventListener('change',renderSelected);
    delegate($('#version-history'),b=>{if(b.dataset.viewVersion){$('#version-select').value=b.dataset.viewVersion;renderSelected();$('#version-preview').scrollIntoView({behavior:'smooth'});}});
    bind('#new-version',()=>{editBasis={versionId:selected.id,revision:detail.versionRevision};editor.fill(selected.content);$('#content-dialog').showModal();});
    bind(form,async()=>{const result=await durable('version:'+qid,'创建新版本',base+'/versions','POST',{content:editor.read(),changeNote:form.elements.changeNote.value,basedOnVersionId:editBasis.versionId,expectedRevision:editBasis.revision});$('#content-dialog').close();await load(result.version.id);notice(result.message||'新版本已保存',result.conflict);},'submit');
    bind('#restore-version',async()=>{if(!await confirmAction('将查看的版本恢复为一个新版本？已有版本和问卷不会被覆盖。'))return;const result=await durable('restore:'+qid,'恢复历史版本',base+'/versions/'+selected.id+'/restore','POST',{basedOnVersionId:detail.currentVersionId,expectedRevision:detail.versionRevision,changeNote:'从页面恢复 v'+selected.versionNumber});await load(result.version.id);notice(result.message,result.conflict);});
    bind('#select-current',async()=>{if(!await confirmAction('将这个版本设为以后选题的推荐版本？已有问卷不变。'))return;const result=await durable('select:'+qid,'选择推荐版本',base+'/current-version','PUT',{versionId:selected.id,expectedCurrentVersionId:detail.currentVersionId,expectedRevision:detail.versionRevision});await load(selected.id);notice(result.message);});
    bind('#diff-form',async()=>{const f=$('#diff-form').elements,data=await api(base+'/version-diff?from='+f.from.value+'&to='+f.to.value);$('#version-diff').innerHTML=data.equal?'<p class="muted">两个版本的内容相同。</p>':data.changes.map(c=>`<div class="diff-row"><h3>${esc(fields[c.field]||c.field)}</h3><div class="two-cols"><pre>${esc(JSON.stringify(c.from,null,2))}</pre><pre>${esc(JSON.stringify(c.to,null,2))}</pre></div></div>`).join('');},'submit');
    bind('#share-form',async()=>{const result=await api(base+'/shares','POST',{recipientUsername:$('#share-form').elements.recipientUsername.value.trim()});await loadShares();notice(result.alreadyActive?'该用户已有有效授权':'共享已建立');},'submit');
    bind('#shares-more',()=>loadShares(true));
    delegate($('#share-history'),async b=>{if(b.dataset.revoke){if(!await confirmAction('撤销这条共享？对方已有问卷和历史回答仍保留。'))return;await api(base+'/shares/'+b.dataset.revoke,'DELETE');}else if(b.dataset.regrant)await api(base+'/shares','POST',{recipientUserId:b.dataset.regrant});await loadShares();});
    bind('#copy-question',async()=>{if(!await confirmAction('创建属于自己的独立副本？副本的版本与统计独立。'))return;const result=await durable('copy:'+qid,'创建独立副本',base+'/copies','POST',{versionId:selected.id});location.href='/questions/'+result.question.id;});
    const surveys=(await api('/api/surveys')).surveys.filter(s=>s.status==='draft');
    $('#import-form').elements.surveyId.innerHTML=surveys.length?options(surveys,s=>s.id,s=>s.title):'<option value="">请先创建草稿问卷</option>';
    bind('#import-form',async()=>{const sid=$('#import-form').elements.surveyId.value;await addSnapshot('/api/surveys/'+sid+'/questions/from-library',{questionId:qid,versionId:selected.id});notice('题目已加入草稿问卷');},'submit');
    const banks=await all('/api/question-banks','banks');$('#add-bank-form').elements.bankId.innerHTML=banks.length?options(banks,b=>b.id,b=>b.name):'<option value="">请先在「我的题库」中新建题库</option>';
    bind('#add-bank-form',async()=>{await api('/api/question-banks/'+$('#add-bank-form').elements.bankId.value+'/items','POST',{questionId:qid,defaultVersionId:selected.id});notice('已加入题库，默认版本为 v'+selected.versionNumber);},'submit');
    try{await load();}catch(error){$('#question-error').hidden=false;$('#question-error').innerHTML=empty('题目当前无法打开',error.message);throw error;}
  }
  async function banks() {
    closeButtons();let rows=[], cursor, selected=null, items=[], itemCursor, editing=false, editingItem;
    const form=$('#bank-form');
    async function load(more=false){const data=await api('/api/question-banks?limit=50'+(more&&cursor?'&before='+cursor:''));rows=more?[...rows,...data.banks]:data.banks;cursor=data.nextBefore;$('#banks-more').hidden=!data.hasMore;renderList();}
    function renderList(){$('#bank-list').innerHTML=rows.length?rows.map(b=>`<button class="bank-choice ${selected?.id===b.id?'active':''}" type="button" data-bank="${b.id}"><strong>${esc(b.name)}</strong><span>${esc(b.description||'暂无说明')}</span></button>`).join(''):'<p class="muted">先新建一个题库，整理常用题目。</p>';}
    async function show(id,more=false){if(!more){selected=(await api('/api/question-banks/'+id)).bank;items=[];}const data=await api('/api/question-banks/'+id+'/items?limit=50'+(more&&itemCursor?'&before='+itemCursor:''));items.push(...data.items);itemCursor=data.nextBefore;$('#items-more').hidden=!data.hasMore;
      $('#bank-empty').hidden=true;$('#bank-detail').hidden=false;$('#bank-name').textContent=selected.name;$('#bank-description').textContent=selected.description;
      $('#bank-items').innerHTML=items.length?items.map(i=>`<article class="bank-item"><h3>${esc(i.displayTitleSnapshot)}</h3><p class="hint">${i.canUse?'默认 v'+i.defaultVersionNumber:'当前不可重新选用 · '+esc(i.reason)}</p><div class="actions wrap">${i.canUse?`<a class="text-link" href="/questions/${esc(i.questionId)}?versionId=${esc(i.defaultVersionId)}">查看与选用 ↗</a> ${button('调整默认版本',`data-default-item="${i.id}"`)}`:`<a class="text-link" href="/questions/${esc(i.questionId)}/statistics">本人历史统计</a>`}${button('移除条目',`data-remove-item="${i.id}"`)}</div></article>`).join(''):'<p class="muted">题库还是空的。从题目详情页加入第一个条目。</p>';renderList();
    }
    delegate($('#bank-list'),b=>b.dataset.bank?show(b.dataset.bank):undefined);
    bind('#create-bank',()=>{editing=false;form.reset();$('#bank-form-title').textContent='新建题库';$('#bank-dialog').showModal();});
    bind('#edit-bank',()=>{editing=true;form.elements.name.value=selected.name;form.elements.description.value=selected.description;$('#bank-form-title').textContent='编辑题库';$('#bank-dialog').showModal();});
    bind(form,async()=>{const data={name:form.elements.name.value,description:form.elements.description.value};if(editing)data.expectedRevision=selected.revision;const result=await api('/api/question-banks'+(editing?'/'+selected.id:''),editing?'PATCH':'POST',data);$('#bank-dialog').close();await load();await show(result.bank.id);notice('题库已保存');},'submit');
    bind('#delete-bank',async()=>{if(!await confirmAction('删除这个题库？原题、版本、已有问卷和回答仍保留。'))return;await api('/api/question-banks/'+selected.id,'DELETE');selected=null;$('#bank-detail').hidden=true;$('#bank-empty').hidden=false;await load();});
    bind('#banks-more',()=>load(true));bind('#items-more',()=>show(selected.id,true));
    delegate($('#bank-items'),async b=>{const item=items.find(i=>i.id===(b.dataset.removeItem||b.dataset.defaultItem));if(!item)return;
      if(b.dataset.removeItem){if(!await confirmAction('从这个题库移除条目？原题和已创建问卷不变。'))return;await api('/api/question-banks/'+selected.id+'/items/'+item.id,'DELETE');await show(selected.id);}
      else {editingItem=item;const data=await versionsFor(item.questionId,item.defaultVersionId);$('#item-form').elements.versionId.innerHTML=options(data.versions,v=>v.id,v=>'v'+v.versionNumber+' · '+v.content.title);$('#item-form').elements.versionId.value=item.defaultVersionId;$('#item-dialog').showModal();}
    });
    bind('#item-form',async()=>{await api('/api/question-banks/'+selected.id+'/items/'+editingItem.id,'PUT',{defaultVersionId:$('#item-form').elements.versionId.value,expectedRevision:editingItem.revision});$('#item-dialog').close();await show(selected.id);notice('默认版本已更新，已有问卷不变');},'submit');
    await load();if(rows.length)await show(rows[0].id);
  }
  function summaryHTML(data) {
    let html=`<p class="hint">${data.answerCount} 项有效回答${data.submissionCount===undefined?'':' · '+data.submissionCount+' 次提交'}</p>`;
    if(data.options)html+=data.options.map(o=>`<div class="bar-row"><div class="bar-label"><span>${esc(o.label)}</span><span>${o.count} 次</span></div><div class="bar-track"><div class="bar-fill" style="width:${data.answerCount?Math.min(100,o.count/data.answerCount*100):0}%"></div></div></div>`).join('')+`<p class="hint">总选择次数 ${data.selectionCount}；多选可大于回答数。</p>`;
    if('mean' in data)html+=`<div class="average">${number(data.mean)}<small>平均值</small></div>`;
    if(data.distribution){const d=data.distribution;html+='<div class="table-scroll"><table><thead><tr><th>数字范围 / 数值</th><th>次数</th></tr></thead><tbody>';
      if(d.bins){html+=`<tr><td>小于 ${esc(d.bins[0])}</td><td>${d.underflow}</td></tr>`+d.counts.map((count,i)=>`<tr><td>[${esc(d.bins[i])}, ${esc(d.bins[i+1])}${i===d.counts.length-1?']':')'}</td><td>${count}</td></tr>`).join('')+`<tr><td>大于 ${esc(d.bins.at(-1))}</td><td>${d.overflow}</td></tr>`;}
      else html+=d.frequencies.map(f=>`<tr><td>${esc(f.value)}</td><td>${f.count}</td></tr>`).join('');html+='</tbody></table></div>';if(d.truncated)html+=`<p class="hint">仅显示前100个数值，另有 ${d.remainingAnswerCount} 项回答未展示。</p>`;
    }
    if(data.texts)html+=`<ul class="stat-values">${data.texts.map(v=>`<li>${esc(v)}</li>`).join('')||'<li>暂无回答</li>'}</ul>${data.textsTruncated?'<p class="hint">仅展示前100条文本，总数不受影响。</p>':''}`;
    return html;
  }
  async function questionStats() {
    const base=questionBase(qid), filter=$('#question-stats-filter'), cform=$('#compatibility-form');let versionRows=[], config=null, groups=[], usageCursor, used=[], owner=false;
    $('#back-question').href='/questions/'+qid;
    function query(){const p=new URLSearchParams();if(filter.elements.versionId.value)p.set('versionId',filter.elements.versionId.value);const raw=filter.elements.bins.value.trim();if(raw){const parts=raw.split(/[,，]/).map(s=>s.trim());if(parts.some(s=>!s||!Number.isFinite(Number(s))))throw new Error('请用逗号分隔有效数字边界');p.set('bins',JSON.stringify(parts.map(Number)));}return p;}
    async function usage(more=false){const p=new URLSearchParams();if(filter.elements.versionId.value)p.set('versionId',filter.elements.versionId.value);if(more&&usageCursor)p.set('before',usageCursor);const data=await api(base+'/usage?'+p);used=more?[...used,...data.surveys]:data.surveys;usageCursor=data.nextBefore;$('#usage-more').hidden=!data.hasMore;
      $('#question-usage').innerHTML=used.length?used.map(s=>`<div class="history-row"><a class="text-link" href="/surveys/${esc(s.surveyId)}/edit">${esc(s.title)} ↗</a><p class="hint">${esc(statuses[s.status]||s.status)} · ${s.instances.length} 个实例</p><ul>${s.instances.map(i=>`<li>版本 ${esc(versionRows.find(v=>v.versionId===i.versionId)?.versionNumber??'历史')} · 实例 <code>${esc(i.instanceId)}</code></li>`).join('')}</ul></div>`).join(''):'<p class="muted">当前范围内还没有本人问卷使用记录。</p>';
    }
    async function load(){const data=await api(base+'/statistics?'+query());$('#question-stat-counts').innerHTML=[['问卷数',data.surveyCount],['题目实例数',data.instanceCount],['提交数',data.submissionCount],['有效回答数',data.answerCount]].map(([label,n])=>`<div><span class="metric-label">${label}</span><strong>${n}</strong></div>`).join('');
      $('#question-stat-note').textContent='兼容配置修订 '+data.configurationRevision+' · 未回答或跳过不计有效答案；各版本提交数可能重叠。'+(Object.keys(data.excludedAnswers).length?' 已排除空白、无可靠来源或无效答案。':'');
      if(!filter.elements.versionId.value){versionRows=data.versions;const selected=filter.elements.versionId.value;filter.elements.versionId.innerHTML='<option value="">全部可见版本</option>'+options(versionRows,v=>v.versionId,v=>'v'+v.versionNumber);filter.elements.versionId.value=selected;}
      $('#overall-statistics').innerHTML=data.overall.map(g=>`<article class="stat-panel"><h3>${esc(metricNames[g.metric])} · ${g.confirmed?esc(g.groupId):'独立版本'}</h3><p class="hint">${g.versionIds.map(id=>'v'+(versionRows.find(v=>v.versionId===id)?.versionNumber??'?')).join('、')}${g.confirmed?' · 所有者已确认':' · 未合并'}</p>${summaryHTML(g)}</article>`).join('')||'<p class="muted">暂无可统计版本。</p>';
      $('#version-statistics').innerHTML=data.versions.map(v=>`<article class="stat-panel"><h3>v${v.versionNumber} · ${esc(types[v.type])}</h3><p class="hint">${v.surveyCount} 份问卷 · ${v.instanceCount} 个实例</p>${summaryHTML(v)}</article>`).join('');await usage();
    }
    function renderGroups(){$('#compatibility-groups').innerHTML=groups.length?groups.map((g,i)=>`<div class="history-row"><strong>${esc(metricNames[g.metric])} · ${esc(g.groupId)}</strong><p>${g.versionIds.map(id=>'v'+(versionRows.find(v=>v.versionId===id)?.versionNumber??'?')).join('、')}</p>${button('移除分组',`data-remove-group="${i}"`)}</div>`).join(''):'<p class="muted">所有版本均按指标独立统计。</p>';}
    async function loadConfig(){try{config=await api(base+'/statistics-configuration');owner=true;}catch(error){if(error.status===404)return;throw error;}
      $('#compatibility-panel').hidden=false;groups=structuredClone(config.events[0]?.groups||[]);renderGroups();
      $('#compatible-versions').innerHTML=versionRows.map(v=>`<label class="inline-check"><input name="version" type="checkbox" value="${esc(v.versionId)}">v${v.versionNumber} · ${esc(types[v.type])}</label>`).join('');
      $('#compatibility-history').innerHTML=config.events.map(e=>`<div class="history-row"><strong>修订 ${e.revision}</strong><p>${esc(e.reason)}</p><p class="hint">${esc(date(e.confirmedAt))} · 确认人 ${esc(e.confirmedBy)} · ${e.groups.length} 个分组</p><ul>${e.groups.map(g=>`<li>${esc(metricNames[g.metric])} · ${esc(g.groupId)}：${g.versionIds.map(id=>"v"+(versionRows.find(v=>v.versionId===id)?.versionNumber??"?")).join("、")}</li>`).join('')}</ul></div>`).join('')||'<p class="muted">尚未配置，默认每版本独立。</p>';
    }
    bind(filter,load,'submit');bind('#refresh-question-stats',load);bind('#usage-more',()=>usage(true));
    delegate($('#compatibility-groups'),b=>{if(b.dataset.removeGroup!==undefined){groups.splice(Number(b.dataset.removeGroup),1);$("#confirm-compatibility-form").elements.confirmed.checked=false;renderGroups();$('#compatibility-preview').textContent='配置已调整，保存前请再次核实。';}});
    bind(cform,async()=>{const f=cform.elements,group={metric:f.metric.value,groupId:f.groupId.value.trim(),versionIds:$$('input[name="version"]:checked',cform).map(i=>i.value)};const candidate=[...groups,group];const data=await api(base+'/statistics-configuration/preview','POST',{groups:candidate});groups=data.groups;$("#confirm-compatibility-form").elements.confirmed.checked=false;renderGroups();$('#compatibility-preview').textContent=data.warnings.length?'结构检查通过；需核实变化：'+data.warnings.map(w=>(metricNames[w.metric]||w.metric)+' / '+w.changedFields.map(k=>fields[k]||k).join('、')).join('；'):'结构检查通过。仍需所有者核实含义并确认。';},'submit');
    bind('#reset-compatibility',async()=>{if(await confirmAction('将待确认配置清空？点击「确认并保存配置」后才生效，旧确认历史保留。')){groups=[];$("#confirm-compatibility-form").elements.confirmed.checked=false;renderGroups();}});
    bind('#confirm-compatibility-form',async()=>{if(!owner)return;const f=$('#confirm-compatibility-form').elements;await durable('compatibility:'+qid,'确认统计兼容性',base+'/statistics-configuration','PUT',{expectedRevision:config.revision,confirmed:f.confirmed.checked,reason:f.reason.value,groups});f.confirmed.checked=false;await load();await loadConfig();notice('统计配置已保存');},'submit');
    await load();await loadConfig();
  }
  // Source picker intentionally uses confirmed server version content, never client snapshots.
  async function picker(survey, reload) {
    const [owned,shared,banks]=await Promise.all([api('/api/questions'),all('/api/shared-questions','shares'),all('/api/question-banks','banks')]);
    const dialog=modal('从题库选题','<label>来源<select name="source"><option value="owned">我的题目</option><option value="shared">收到的共享</option>'+options(banks,b=>'bank:'+b.id,b=>'题库 · '+b.name)+'</select></label><label>题目<select name="question" required></select></label><label>版本<select name="version" required></select></label><div data-picker-preview></div><label class="inline-check"><input name="required" type="checkbox">在这份问卷中必答</label>','加入问卷',async(form,d)=>{
      if(!state.version)throw new Error('请先选择可用题目和版本');const payload={required:form.elements.required.checked};
      const path=state.item?'/api/question-banks/'+state.bank+'/items/'+state.item.id+'/select':'/api/surveys/'+surveyId+'/questions/from-library';
      if(state.item)payload.surveyId=surveyId;else Object.assign(payload,{questionId:state.id,versionId:form.elements.version.value});
      await addSnapshot(path,payload);d.close();await reload();notice('题目已加入问卷，来源版本已固定');
    });
    const form=$('form',dialog), state={id:null,version:null,item:null,bank:null,rows:[]};let generation=0;
    async function setQuestion(){const current=++generation;state.version=null;const id=form.elements.question.value,row=state.rows.find(r=>r.id===id);form.elements.version.innerHTML='';$('[data-picker-preview]',dialog).textContent='正在加载…';
      if(!row){$('[data-picker-preview]',dialog).textContent='此来源中没有可选题目。';return;}
      try{const result=await versionsFor(row.questionId||row.id,row.defaultVersionId);if(current!==generation)return;state.id=row.questionId||row.id;state.item=row.defaultVersionId?row:null;
        const available=state.item?result.versions.filter(v=>v.id===row.defaultVersionId):result.versions;
        form.elements.version.innerHTML=options(available,v=>v.id,v=>'v'+v.versionNumber+' · '+v.content.title);if(!state.item)form.elements.version.value=result.question.currentVersionId;state.versions=available;setVersion();
      }catch(error){if(current===generation){$('[data-picker-preview]',dialog).textContent=error.message;throw error;}}
    }
    function setVersion(){state.version=state.versions.find(v=>v.id===form.elements.version.value);form.elements.required.checked=state.version?.content.required??false;$('[data-picker-preview]',dialog).innerHTML=state.version?previewContent(state.version):'<p>该版本当前不可选用。</p>';}
    async function setSource(){const source=form.elements.source.value, current=++generation, bank=source.startsWith('bank:')?source.slice(5):null;state.version=null;form.elements.question.innerHTML='';form.elements.version.innerHTML='';$('[data-picker-preview]',dialog).textContent='正在读取来源…';
      const rows=bank?(await all('/api/question-banks/'+bank+'/items','items')).filter(i=>i.canUse):source==='owned'?owned.questions:shared.filter(s=>s.canUse).map(s=>s.question);
      if(current!==generation)return;state.bank=bank;state.rows=rows;
      form.elements.question.innerHTML=options(state.rows,r=>r.id,r=>r.title||r.displayTitleSnapshot);await setQuestion();
    }
    bind(form.elements.source,setSource,'change');bind(form.elements.question,setQuestion,'change');form.elements.version.addEventListener('change',setVersion);await setSource();
  }
  function editorTools(survey, reload) {
    $('#pick-library-question').hidden=!survey.canEdit;
    $$('.question-item',$('#question-list')).forEach((article,index)=>{
      const q=survey.questions[index], root=document.createElement('div');root.className='source-tools';
      root.innerHTML=(q.sourceQuestionId?`<p class="source-note">题库来源 · ${link(q.sourceQuestionId,'查看题目')} · <a class="text-link" href="/questions/${esc(q.sourceQuestionId)}/statistics">跨问卷统计</a><br><span class="hint">固定版本：<code>${esc(q.sourceVersionId)}</code></span></p>`:'<p class="hint">问卷独立题目 · 未关联题库统计</p>')+`<div class="actions wrap">${button('另存为独立题目','data-save-library')}${survey.canEdit&&q.sourceQuestionId?button('切换来源版本','data-switch-source'):''}</div>`;
      article.append(root);
      bind($('[data-save-library]',root),()=>modal('另存为独立题目','<p class="hint">保留原问卷和历史回答，不自动将旧回答关联到新题统计。</p><label>管理名称<input name="title" maxlength="200" value="'+esc(q.title)+'" required></label>','保存到题目库',async(form,dialog)=>{await durable('save:'+surveyId+':'+q.id,'旧题保存到题目库','/api/surveys/'+surveyId+'/questions/'+q.id+'/save-to-library','POST',{title:form.elements.title.value});dialog.close();notice('已保存为独立题目，可在「题目库」查看');}));
      bind($('[data-switch-source]',root),async()=>{const result=await versionsFor(q.sourceQuestionId,q.sourceVersionId);modal('切换来源版本','<p class="hint">保留实例与必答设置；如与现有跳转规则冲突，服务器会拒绝。</p><label>目标版本<select name="version" required>'+options(result.versions,v=>v.id,v=>'v'+v.versionNumber+' · '+v.content.title)+'</select></label>','切换版本',async(form,dialog)=>{await api('/api/surveys/'+surveyId+'/questions/'+q.id+'/source-version','PUT',{versionId:form.elements.version.value});dialog.close();await reload();notice('来源版本已切换');});});
    });
  }
  return {library,question,banks,questionStats,picker,editorTools,renderPending};
})();
