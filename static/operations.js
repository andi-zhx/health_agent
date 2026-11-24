(function () {
  'use strict';
  let bridge, page = 1, rows = [], overviewVersion = 0, outcomesVersion = 0;
  const $ = id => document.getElementById(id);
  const escape = value => String(value == null ? '' : value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const percent = value => value == null ? '—' : value + '%';
  const colors = ['#608f74', '#acc49a', '#e0d8bb', '#c78b71'];
  const iconPaths = [
    '<path d="M8 20h8M9 17h6V9H9zM12 9V5M8 5c-2-2 2-2 0-4M16 6c-2-2 2-2 0-4"/>',
    '<rect x="3" y="6" width="18" height="13" rx="6"/><circle cx="10" cy="12.5" r="3"/><path d="M15 10h3M15 14h3M6 21v-2m12 2v-2"/>',
    '<path d="M8 15c0-3-3-3-3-7a7 7 0 0 1 14 0c0 5-4 5-4 9a4 4 0 0 1-8 0M9 8a3 3 0 0 1 6 0c0 2-3 2-3 5"/>',
    '<rect x="7" y="4" width="10" height="11" rx="3"/><path d="M4 10v8h16v-8M7 18v3m10-3v3M10 8h4M10 11h4"/>'
  ];
  function year(id) { return $(id).value || String(new Date().getFullYear()); }
  function message(id, text, error) { $(id).innerHTML = text ? '<div class="msg ' + (error ? 'err' : 'ok') + '">' + escape(text) + '</div>' : ''; }
  function demoRibbon(demo) { return demo ? '<div class="demo-ribbon"><strong>演示环境 · 100 位虚构干部</strong><span>仅用于体验与系统建设展示，不能作为真实业绩或医学疗效数据。</span></div>' : ''; }
  function kpi(label, value, unit, caption, accent) {
    return '<div class="annual-kpi'+(accent?' accent':'')+'"><div class="kpi-label">'+escape(label)+'</div><div class="kpi-number">'+escape(value == null ? '—' : value)+'<small>'+escape(unit)+'</small></div><div class="kpi-caption">'+escape(caption)+'</div></div>';
  }
  function heading(title, subtitle, action, target) {
    return '<div class="annual-section-title"><h2>'+escape(title)+'</h2>'+(action?'<button class="text-action" data-ops-page="'+escape(target)+'">'+escape(action)+' ↗</button>':'<p>'+escape(subtitle)+'</p>')+'</div>';
  }
  function bars(items, total, customColors) {
    const max = Math.max(1, total || 0);
    return '<div class="horizontal-summary">'+items.map((item,i)=>'<div class="summary-line"><span>'+escape(item.name)+'</span><div class="summary-track"><span style="width:'+Math.min(100,item.count/max*100)+'%;background:'+(customColors ? customColors[i%customColors.length] : '#82a58a')+'"></span></div><strong>'+escape(item.count)+' 人</strong></div>').join('')+'</div>';
  }
  function renderOverview(data) {
    const s = data.summary;
    $('environment-badge').classList.toggle('hide', !data.demo);
    $('overview-subtitle').textContent = data.unit_name + ' · ' + data.year + ' 年度 · 统计截至 ' + data.cutoff;
    setYears(data.years, data.year);
    let html = demoRibbon(data.demo);
    html += '<section class="annual-hero"><div><div class="eyebrow">健康服务建设 · 年度回顾</div><h2>让健康服务，有记录、有反馈、有改进。</h2><div class="service-chain"><span>干部建档</span><i>→</i><span>现场 / 上门服务</span><i>→</i><span>体验反馈</span><i>→</i><span>持续回访</span></div></div><div class="hero-year">'+data.year+'<small>CARE, CONNECTED.</small></div></section>';
    html += '<div class="annual-kpis">'+kpi('服务对象建档',s.customers,'人',s.assessed+' 人已评估 · 档案覆盖 '+percent(s.assessment_coverage))+
      kpi('年度完成服务',s.services,'人次','覆盖 '+s.served_people+' 人 · 现场 '+s.onsite+' / 上门 '+s.home)+
      kpi('服务后反馈覆盖',percent(s.feedback_coverage),'',s.linked_feedback+' / '+s.services+' 次已完成服务有关联反馈')+
      kpi('本人自述改善',percent(s.improvement_rate),'',s.improved+' / '+s.valid_feedback+' 条有效反馈 · 非临床疗效',true)+'</div>';
    html += heading('现场设备与服务','完成服务人次 · 保留所有原有项目')+'<div class="device-review-grid">';
    data.devices.forEach((device,i)=>{
      html += '<article class="device-review"><div class="device-review-head"><div class="device-icon"><svg viewBox="0 0 24 24" aria-hidden="true">'+iconPaths[i]+'</svg></div><div><h3>'+escape(device.name)+'</h3><p>'+device.available+' / '+device.units+' 台设备当前可用</p></div></div><div class="device-review-values"><strong>'+device.services+' <span>人次</span></strong><span>覆盖 '+device.people+' 人</span></div><div class="device-review-foot"><span>自述改善 '+percent(device.improvement_rate)+' · n='+device.feedback+'</span><button data-ops-project="'+escape(device.name)+'">查看反馈 ↗</button></div></article>';
    });
    html += '</div><div class="review-grid"><section class="review-panel"><div class="panel-head"><h2>服务开展趋势</h2><div class="chart-legend"><span style="--legend-color:#69947d">现场服务</span><span style="--legend-color:#d2ddbc">上门服务</span></div></div><p class="panel-subtitle">已完成服务人次 · 当前年度未结束，未来月份不计入</p><div class="annual-bar-chart" role="img" aria-label="'+escape(data.months.map(m=>m.month+'月：'+(m.services==null?'尚未到来':m.services+'人次')).join('；'))+'">';
    const maxMonth = Math.max(1,...data.months.map(m=>Math.max(m.onsite||0,m.home||0)));
    data.months.forEach(m=>{html+='<div class="annual-month'+(m.services==null?' future':'')+'"><div class="month-bars"><small class="month-value">'+(m.services==null?'—':m.services)+'</small><span style="height:'+((m.onsite||0)/maxMonth*115)+'px"></span><span class="home" style="height:'+((m.home||0)/maxMonth*115)+'px"></span></div><span>'+m.month+'月</span></div>';});
    html += '</div></section><section class="review-panel"><div class="panel-head"><h2>干部体验反馈</h2><button class="btn btn-outline btn-small" data-ops-page="outcomes">体验与回访 ↗</button></div><p class="panel-subtitle">'+s.valid_feedback+' 条有效改善反馈 · 本人主观感受</p><div class="annual-outcome-layout"><div class="outcome-ring"><svg viewBox="0 0 120 120" aria-hidden="true"><circle cx="60" cy="60" r="49" fill="none" stroke="#eef3e9" stroke-width="12"/>';
    let offset=0;
    data.outcomes.forEach((item,i)=>{const length=s.valid_feedback?item.count/s.valid_feedback*307.876:0;html+='<circle cx="60" cy="60" r="49" fill="none" stroke="'+colors[i]+'" stroke-width="12" stroke-dasharray="'+length+' '+(307.876-length)+'" stroke-dashoffset="'+(-offset)+'"/>';offset+=length;});
    html += '</svg><div class="ring-center"><strong>'+percent(s.improvement_rate)+'</strong><small>自述改善比例</small></div></div><div class="outcome-legend">'+data.outcomes.map((item,i)=>'<div class="outcome-legend-row"><i style="--swatch:'+colors[i]+'"></i><span>'+escape(item.name)+'</span><strong>'+item.count+' 条</strong></div>').join('')+'</div></div><div class="review-guardrails"><span>满意度 '+(s.satisfaction==null?'—':s.satisfaction+' / 5')+' · n='+s.rated+'</span><button data-ops-state="adverse">不适 / 加重 '+s.adverse+' 条</button><button data-ops-state="due">到期待回访 '+s.followup_due+' 条</button></div></section></div>';
    html += '<div class="review-grid"><section class="review-panel"><div class="panel-head"><h2>健康档案与随访关注</h2><button class="btn btn-outline btn-small" data-ops-page="portrait">详细画像 ↗</button></div><p class="panel-subtitle">每人截至统计日最新评估 · 用于服务管理，不作疾病诊断</p>'+bars(data.management,s.customers,['#91ae90','#b0bf96','#c2a680','#ced5bd','#dfe5d8'])+'<div class="health-coverage-note">'+data.health_signals.map(item=>escape(item.label)+' '+item.observed+' / '+s.assessed+' 人有监测结果').join('　')+'</div></section><section class="review-panel"><div class="panel-head"><h2>已记录疾病分布</h2><span class="section-note">可多选 · 按人数</span></div><p class="panel-subtitle">'+data.disease_recorded+' 人有明确病史记录；空白档案不等同于无疾病</p>'+(data.diseases.length?bars(data.diseases.slice(0,6),Math.max(...data.diseases.map(r=>r.count))):'<div class="empty-state">暂无明确病史标签，请先完善健康档案。</div>')+'</section></div>';
    html += '<section class="recommendations">'+heading('下一步，如何把服务做得更好','依据当前记录生成 · 供运营人员参考')+'<div class="recommendation-grid">';
    data.recommendations.forEach((r,i)=>{html+='<article class="recommendation"><div class="recommendation-index">'+String(i+1).padStart(2,'0')+'</div><div><h3>'+escape(r.title)+'<span class="priority">'+escape(r.priority)+'</span></h3><p class="evidence">'+escape(r.evidence)+'</p><p>'+escape(r.action)+'</p><button data-ops-page="'+escape(r.target)+'">前往处理 →</button></div></article>';});
    html += '</div></section><details class="annual-notes"><summary>统计口径与数据说明</summary><dl>'+data.definitions.map(item=>'<dt>'+escape(item[0])+'</dt><dd>'+escape(item[1])+'</dd>').join('')+'<dt>关注分组</dt><dd>多项已记录病史或多项监测异常归为重点关注；其他病史、监测异常或睡眠问题归为常规随访。信息不足单列，不以正常代替缺失。</dd></dl></details><div class="annual-footer"><span>档案 → 服务 → 反馈 → 回访，形成可追溯的服务闭环</span><span>'+data.year+' · HEALTH CARE</span></div>';
    $('overview-content').innerHTML=html;
    $('overview-content').setAttribute('aria-busy','false');
  }
  function setYears(years, selected) {
    ['overview-year','outcomes-year'].forEach(id=>{
      const previous=$(id).value;
      $(id).innerHTML=years.map(y=>'<option value="'+y+'">'+y+' 年</option>').join('');
      $(id).value=years.includes(Number(previous)) ? previous : String(selected);
    });
  }
  function loadOverview() {
    const version=++overviewVersion;
    message('overview-message','');
    $('overview-content').setAttribute('aria-busy','true');
    $('overview-content').innerHTML='<div class="loading-state">正在汇总年度服务记录…</div>';
    return bridge.get('/api/operations/overview?year='+year('overview-year')).then(data=>{
      if(version!==overviewVersion)return;
      if(data.error){$('overview-content').innerHTML='';$('overview-content').setAttribute('aria-busy','false');message('overview-message',data.error,true);return;}
      renderOverview(data);
    });
  }
  function loadOutcomes() {
    const version=++outcomesVersion;
    const params=new URLSearchParams({year:year('outcomes-year'),page,search:$('outcomes-search').value,project:$('outcomes-project').value,state:$('outcomes-state').value});
    $('outcomes-list').innerHTML='<tr><td colspan="7">正在加载体验反馈…</td></tr>';
    return bridge.get('/api/operations/experiences?'+params).then(data=>{
      if(version!==outcomesVersion)return;
      if(data.error){$('outcomes-list').innerHTML='<tr><td colspan="7">加载失败，请重试。</td></tr>';message('outcomes-message',data.error,true);return;}
      $('outcomes-message').innerHTML=demoRibbon(data.demo);
      const s=data.summary;
      $('outcomes-summary').innerHTML=kpi('全年有效改善反馈',s.valid_feedback,'条','下方列表可按项目和回访状态筛选')+kpi('体验满意度',s.satisfaction==null?'—':s.satisfaction,'/ 5',s.rated+' 条有评分记录')+kpi('到期待回访',s.followup_due,'条',s.followup_unscheduled+' 条尚未安排回访日期',true)+kpi('不适 / 加重反馈',s.adverse,'条','优先核实与专业评估，不忽略负向感受');
      rows=data.items;page=data.page;
      $('outcomes-list').innerHTML=rows.length?rows.map(r=>{
        const pair=r.before_score==null?'—':'<strong class="score-pair">'+r.before_score+' <span>→ '+r.after_score+'</span></strong>';
        const cls=r.improvement_status==='加重'?'alert':r.improvement_status==='无改善'?'neutral':'';
        return '<tr><td><strong>'+escape(r.customer_name)+'</strong><span class="cell-sub">'+escape(r.service_time.slice(0,16))+'</span></td><td>'+escape(r.service_project)+'<span class="cell-sub">'+(r.service_type==='home_appointments'?'上门服务':'现场服务')+'</span></td><td>'+pair+'<span class="cell-sub">'+escape(r.experience_dimension||'未记录维度')+'</span></td><td><span class="outcome-pill '+cls+'">'+escape(r.improvement_status)+'</span>'+(r.adverse_event==='有不适'?'<span class="cell-sub">已登记不适反馈</span>':'')+'</td><td>'+(r.satisfaction_score==null?'未评价':r.satisfaction_score+' / 5')+'</td><td><span class="outcome-pill '+(r.followup_status==='待回访'?'waiting':'')+'">'+escape(r.followup_status||'待回访')+'</span><span class="cell-sub">'+escape(r.followup_status==='已回访'?(r.followup_completed_at||'').slice(0,16):r.followup_date||'待安排日期')+'</span></td><td class="outcome-actions"><button class="btn btn-outline" data-experience-view="'+r.id+'">查看</button> <button class="btn btn-outline" data-experience-edit="'+r.id+'">编辑</button> '+(r.followup_status==='待回访'?'<button class="btn btn-primary" data-experience-followup="'+r.id+'">回访</button>':'')+'</td></tr>';
      }).join(''):'<tr><td colspan="7" class="empty-state">当前条件下暂无体验记录。可登记体验，或在原“理疗记录”中查询待填写服务。</td></tr>';
      $('outcomes-pagination').innerHTML='<span>共 '+data.total+' 条 · '+page+' / '+data.pages+' 页</span><button data-outcome-page="'+(page-1)+'" '+(page<=1?'disabled':'')+'>上一页</button><button data-outcome-page="'+(page+1)+'" '+(page>=data.pages?'disabled':'')+'>下一页</button>';
    });
  }
  function toLocal(value){return String(value||'').replace(' ','T').slice(0,16);}
  const fields={'experience_dimension':'experience-dimension','before_score':'experience-before','after_score':'experience-after','satisfaction_score':'experience-satisfaction','adverse_event':'experience-adverse','adverse_notes':'experience-adverse-notes','followup_status':'experience-followup-status','followup_completed_at':'experience-followup-completed','followup_notes':'experience-followup-notes'};
  function fillExperience(record){
    for(const [key,id] of Object.entries(fields)) $(id).value=key==='followup_completed_at'?toLocal(record[key]):record[key]??(key==='adverse_event'?'未询问':key==='followup_status'?'待回访':'');
    message('experience-form-message','');
  }
  function collectExperience(){const data={};for(const [key,id] of Object.entries(fields))data[key]=$(id).value;return data;}
  function localNow(){const d=new Date();return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0')+'T'+String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0');}
  function init(api){
    bridge=api;
    setYears([new Date().getFullYear(),new Date().getFullYear()-1],new Date().getFullYear());
    $('overview-year').addEventListener('change',loadOverview);
    $('btn-annual-report').addEventListener('click',()=>window.open('/api/operations/report?year='+year('overview-year'),'_blank','noopener'));
    $('btn-annual-export').addEventListener('click',()=>{window.location.href='/api/operations/export?year='+year('overview-year');});
    $('overview-content').addEventListener('click',event=>{
      const button=event.target.closest('button');if(!button)return;
      if(button.dataset.opsProject||button.dataset.opsState){$('outcomes-year').value=year('overview-year');$('outcomes-project').value=button.dataset.opsProject||'';$('outcomes-state').value=button.dataset.opsState||'';$('outcomes-search').value='';page=1;bridge.showPage('outcomes');}
      else if(button.dataset.opsPage)bridge.showPage(button.dataset.opsPage);
    });
    $('btn-new-experience').addEventListener('click',()=>bridge.openImprovementModal({service_time:localNow()},'登记服务体验'));
    ['outcomes-year','outcomes-project','outcomes-state'].forEach(id=>$(id).addEventListener('change',()=>{page=1;loadOutcomes();}));
    $('btn-outcomes-search').addEventListener('click',()=>{page=1;loadOutcomes();});
    $('outcomes-search').addEventListener('keydown',event=>{if(event.key==='Enter'){page=1;loadOutcomes();}});
    $('btn-outcomes-reset').addEventListener('click',()=>{['outcomes-search','outcomes-project','outcomes-state'].forEach(id=>$(id).value='');page=1;loadOutcomes();});
    $('outcomes-pagination').addEventListener('click',event=>{const b=event.target.closest('[data-outcome-page]');if(b&&!b.disabled){page=Number(b.dataset.outcomePage);loadOutcomes();}});
    $('outcomes-list').addEventListener('click',event=>{
      const button=event.target.closest('button');if(!button)return;
      const id=button.dataset.experienceView||button.dataset.experienceEdit||button.dataset.experienceFollowup;
      const record=rows.find(r=>String(r.id)===id);if(!record)return;
      if(button.dataset.experienceFollowup){$('followup-record-id').value=record.id;$('followup-context').textContent=record.customer_name+' · '+record.service_project;$('followup-completed').value=localNow();$('followup-result').value='';message('followup-message','');$('modal-followup').classList.remove('hide');$('followup-result').focus();}
      else bridge.openImprovementModal(record,button.dataset.experienceView?'体验记录详情':'编辑体验记录',{viewOnly:!!button.dataset.experienceView});
    });
    $('btn-followup-cancel').addEventListener('click',()=>$('modal-followup').classList.add('hide'));
    $('followup-form').addEventListener('submit',event=>{
      event.preventDefault();const button=$('btn-followup-save');button.disabled=true;
      bridge.post('/api/improvement-records/'+$('followup-record-id').value+'/followup',{followup_status:'已回访',followup_completed_at:$('followup-completed').value,followup_notes:$('followup-result').value}).then(result=>{
        if(result.error){message('followup-message',result.error,true);return;}
        $('modal-followup').classList.add('hide');loadOutcomes();
      }).finally(()=>button.disabled=false);
    });
    document.addEventListener('experience-saved',()=>{if(!$('page-outcomes').classList.contains('hide'))loadOutcomes();if(!$('page-overview').classList.contains('hide'))loadOverview();});
  }
  window.HealthOperations={init,loadOverview,loadOutcomes,fillExperience,collectExperience};
})();
