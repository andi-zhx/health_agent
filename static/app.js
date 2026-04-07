(function () {
  const API = '';
  function parseJsonResponse(r) {
    return r.text().then(function (text) {
      if (!text) return {};
      try {
        return JSON.parse(text);
      } catch (e) {
        return { error: '服务返回异常，请刷新后重试' };
      }
    });
  }

  function showLoginScreen(msg) {
    var loginScreen = document.getElementById('login-screen');
    var appShell = document.getElementById('app-shell');
    if (loginScreen) loginScreen.classList.remove('hide');
    if (appShell) appShell.classList.add('hide');
    if (msg) showMsg('login-msg', msg, true);
  }

  function requestJson(url, options) {
    return fetch(API + url, options || {}).then(function (response) {
      return parseJsonResponse(response).then(function (data) {
        if (response.status === 401 && url !== '/api/auth/login') {
          showLoginScreen((data && data.error) || '未登录或登录已失效，请重新登录');
        }
        return data;
      });
    }).catch(function () {
      return { error: '网络请求失败，请稍后重试' };
    });
  }

  function get(url) { return requestJson(url); }
  function post(url, body) { return requestJson(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }); }
  function put(url, body) { return requestJson(url, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }); }

  function toList(data) {
    return Array.isArray(data) ? data : [];
  }

  function showPage(name) {
    document.querySelectorAll('.page').forEach(function (el) { el.classList.add('hide'); });
    document.querySelectorAll('.sidebar a').forEach(function (a) { a.classList.remove('active'); });
    var page = document.getElementById('page-' + name);
    var link = document.querySelector('[data-page="' + name + '"]');
    if (page) page.classList.remove('hide');
    if (link) link.classList.add('active');
    if (name === 'home') loadStats();
    if (name === 'customers') loadCustomers();
    if (name === 'health') loadHealthPage();
    if (name === 'portrait') loadPortraitPage();
    if (name === 'appointments') loadAppointmentsPage();
    if (name === 'home-appointments') loadHomeAppointmentsPage();
    if (name === 'usage') loadUsagePage();
    if (name === 'surveys') loadSurveysPage();
    if (name === 'query-export') loadQueryExportPage();
  }

  function loadQueryExportPage() {
    fillCustomerSelect('qe-customer');
    get('/api/system/backup-path').then(function (res) {
      if (!res || res.error) return;
      document.getElementById('backup-path').value = res.backup_directory || '';
    });
  }

  function loadStats() {
    renderCurrentDate();
    get('/api/dashboard/stats').then(function (data) {
      var html = [
        { num: data.total_customers, label: '客户总数' },
        { num: data.today_appointments, label: '今日预约' }
      ].map(function (s) { return '<div class="stat-box"><div class="num">' + s.num + '</div><div class="label">' + s.label + '</div></div>'; }).join('');
      document.getElementById('stats').innerHTML = html;
    }).catch(function () {});

    get('/api/dashboard/analytics' + buildEquipmentRangeQuery()).then(function (data) {
      renderAppointmentTrend(data.appointment_trend || []);
      renderEquipmentUsageTop(data.equipment_usage_top || []);
      renderSatisfactionSummary(data.satisfaction || {}, data.customer_activity || {});
    }).catch(function () {
      document.getElementById('appointment-trend').innerHTML = '<p style="color:#666">暂无数据</p>';
      document.getElementById('equipment-usage-top').innerHTML = '<tr><td colspan="3">暂无数据</td></tr>';
      document.getElementById('satisfaction-summary').innerHTML = '<tr><td>暂无数据</td><td>-</td></tr>';
    });
  }

  function renderAppointmentTrend(list) {
    var box = document.getElementById('appointment-trend');
    if (!box) return;
    if (!list.length) {
      box.innerHTML = '<p style="color:#666">暂无预约数据</p>';
      return;
    }
    var max = Math.max.apply(null, list.map(function (x) { return x.count || 0; }).concat([1]));
    box.innerHTML = list.map(function (x) {
      var pct = Math.round(((x.count || 0) / max) * 100);
      return '<div class="trend-bar"><div class="date">' + x.date + '</div><div class="bar"><span style="width:' + pct + '%"></span></div><div class="value">' + (x.count || 0) + '</div></div>';
    }).join('');
  }

  function renderCurrentDate() {
    var box = document.getElementById('current-date');
    if (!box) return;
    var now = new Date();
    box.textContent = now.getFullYear() + '年' + (now.getMonth() + 1) + '月' + now.getDate() + '日';
  }

  function buildEquipmentRangeQuery() {
    var start = (document.getElementById('equipment-range-start') || {}).value || '';
    var end = (document.getElementById('equipment-range-end') || {}).value || '';
    var params = [];
    if (start) params.push('equipment_start_date=' + encodeURIComponent(start));
    if (end) params.push('equipment_end_date=' + encodeURIComponent(end));
    return params.length ? ('?' + params.join('&')) : '';
  }

  function renderEquipmentUsageTop(list) {
    var tbody = document.getElementById('equipment-usage-top');
    if (!tbody) return;
    if (!list.length) {
      tbody.innerHTML = '<tr><td colspan="3">暂无数据</td></tr>';
      return;
    }
    tbody.innerHTML = list.map(function (x) {
      return '<tr><td>' + (x.equipment_name || '-') + '</td><td>' + (x.usage_count || 0) + '</td><td>' + (x.total_duration_minutes || 0) + '</td></tr>';
    }).join('');
  }

  function renderSatisfactionSummary(satisfaction, activity) {
    var tbody = document.getElementById('satisfaction-summary');
    if (!tbody) return;
    function n(v) { return v == null ? '-' : v; }
    var rows = [
      ['调查样本数', n(satisfaction.survey_count)],
      ['综合满意度(均分)', n(satisfaction.avg_overall)],
      ['服务评分(均分)', n(satisfaction.avg_service)],
      ['设备评分(均分)', n(satisfaction.avg_equipment)],
      ['环境评分(均分)', n(satisfaction.avg_environment)],
      ['人员评分(均分)', n(satisfaction.avg_staff)],
      ['活跃客户占比', (activity.total_customers ? Math.round((activity.active_customers || 0) * 100 / activity.total_customers) : 0) + '%']
    ];
    tbody.innerHTML = rows.map(function (r) { return '<tr><td>' + r[0] + '</td><td>' + r[1] + '</td></tr>'; }).join('');
  }

  function fillCustomerSelect(selId) {
    get('/api/customers').then(function (list) {
      var sel = document.getElementById(selId);
      if (!sel) return;
      var old = sel.value;
      sel.innerHTML = '<option value="">请选择客户</option>' + toList(list).map(function (c) { return '<option value="' + c.id + '">' + c.name + ' ' + (c.phone || '') + '</option>'; }).join('');
      if (old) sel.value = old;
    });
  }

  function fillEquipmentSelect(selId) {
    return get('/api/equipment').then(function (list) {
      appointmentEquipment = toList(list);
      var sel = document.getElementById(selId);
      if (!sel) return;
      var old = sel.value;
      sel.innerHTML = '<option value="">请选择设备</option>' + appointmentEquipment.map(function (e) { return '<option value="' + e.id + '">' + e.name + '</option>'; }).join('');
      if (old) sel.value = old;
    });
  }

  function fillProjectSelect(selId, enabledOnly, scene) {
    var path = enabledOnly ? '/api/projects/enabled' : '/api/projects';
    if (scene) {
      path += '?scene=' + encodeURIComponent(scene);
    }
    return get(path).then(function (list) {
      var sel = document.getElementById(selId);
      if (!sel) return;
      var old = sel.value;
      var projects = toList(list);
      if (selId === 'apt-project') {
        projects = projects.filter(function (p) { return projectEquipmentMap[p.name]; });
        appointmentProjects = projects;
      }
      sel.innerHTML = '<option value="">请选择项目</option>' + projects.map(function (p) { return '<option value="' + p.id + '">' + p.name + '</option>'; }).join('');
      if (old) sel.value = old;
    });
  }

  function fillStaffSelect(selId) {
    get('/api/staff/available').then(function (list) {
      var sel = document.getElementById(selId);
      if (!sel) return;
      var old = sel.value;
      sel.innerHTML = '<option value="">不指定</option>' + toList(list).map(function (s) { return '<option value="' + s.id + '">' + s.name + '</option>'; }).join('');
      if (old) sel.value = old;
    });
  }


  var pendingAction = null;
  var customerEditSnapshot = null;
  var selectedHealthDetailId = '';
  var editingHealthSnapshot = null;
  var appointmentEditId = null;
  var appointmentSlots = [];
  var homeAppointmentEditId = null;
  var appointmentProjects = [];
  var appointmentEquipment = [];
  var healthCustomerList = [];
  var projectEquipmentMap = { '听力测试': '听力耳机', '高压氧仓': '高压氧仓', '艾灸': '艾灸', '按摩': '按摩机' };

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function selectedCustomerName() {
    var sel = document.getElementById('health-customer');
    if (!sel || sel.selectedIndex < 0) return '';
    return sel.options[sel.selectedIndex].text || '';
  }

  function renderHealthCustomerSelect(keyword) {
    var sel = document.getElementById('health-customer');
    if (!sel) return;
    var old = sel.value;
    var q = String(keyword || '').trim();
    var matched = healthCustomerList.filter(function (c) {
      return !q || String(c.name || '').indexOf(q) !== -1;
    });
    sel.innerHTML = '<option value="">请选择客户</option>' + matched.map(function (c) {
      return '<option value="' + c.id + '">' + c.name + ' ' + (c.phone || '') + '</option>';
    }).join('');
    if (old && matched.some(function (c) { return String(c.id) === String(old); })) {
      sel.value = old;
    }
  }

  function initHealthCustomerPicker() {
    get('/api/customers').then(function (list) {
      healthCustomerList = toList(list);
      var searchInput = document.getElementById('health-customer-search');
      renderHealthCustomerSelect(searchInput ? searchInput.value : '');
    });
  }

  function setHealthEditMode(isEditing) {
    var cancelBtn = document.getElementById('btn-health-cancel-edit');
    if (!cancelBtn) return;
    cancelBtn.style.display = isEditing ? 'inline-flex' : 'none';
  }

  function clearHealthEditState() {
    editingHealthSnapshot = null;
    setHealthEditMode(false);
  }

  function openConfirmModal(title, rows, onConfirm) {
    pendingAction = onConfirm;
    document.getElementById('modal-confirm-title').textContent = title;
    document.getElementById('modal-confirm-content').innerHTML = rows.map(function (row) {
      return '<div><strong>' + escapeHtml(row[0]) + '：</strong>' + escapeHtml(row[1] || '-') + '</div>';
    }).join('');
    document.getElementById('modal-edit-confirm').classList.remove('hide');
  }

  function closeConfirmModal() {
    pendingAction = null;
    document.getElementById('modal-edit-confirm').classList.add('hide');
  }

  function loadCustomers() {
    var q = document.getElementById('customer-search').value;
    get('/api/customers' + (q ? '?search=' + encodeURIComponent(q) : '')).then(function (list) {
      var tbody = document.getElementById('customer-list');
      tbody.innerHTML = toList(list).map(function (c) {
        return '<tr><td>' + c.name + '</td><td>' + (c.id_card || '') + '</td><td>' + (c.phone || '') + '</td><td><button class="btn btn-small btn-primary" data-edit="' + c.id + '">编辑</button></td></tr>';
      }).join('');
      tbody.querySelectorAll('[data-edit]').forEach(function (btn) {
        btn.addEventListener('click', function () { openCustomerModal(btn.dataset.edit); });
      });
    });
  }

  function showMsg(id, text, isErr) {
    var el = document.getElementById(id);
    if (!el) return;
    el.innerHTML = text ? '<div class="msg ' + (isErr ? 'err' : 'ok') + '">' + text + '</div>' : '';
  }

  function isPastDate(dateStr) {
    if (!dateStr) return false;
    var todayDate = new Date();
    todayDate.setHours(0, 0, 0, 0);
    var inputDate = new Date(dateStr + 'T00:00:00');
    return inputDate < todayDate;
  }

  function openCustomerModal(id) {
    document.getElementById('modal-customer-id').value = id || '';
    document.getElementById('modal-customer-title').textContent = id ? '编辑客户' : '新增客户';
    if (id) {
      get('/api/customers/' + id).then(function (c) {
        document.getElementById('mc-name').value = c.name || '';
        document.getElementById('mc-id_card').value = c.id_card || '';
        document.getElementById('mc-phone').value = c.phone || '';
        document.getElementById('mc-address').value = c.address || '';
        document.getElementById('mc-gender').value = c.gender || '';
        document.getElementById('mc-birth_date').value = (c.birth_date || '').slice(0, 10);
      });
    } else {
      ['mc-name', 'mc-id_card', 'mc-phone', 'mc-address', 'mc-gender', 'mc-birth_date'].forEach(function (k) {
        var e = document.getElementById(k);
        if (e) e.value = e.tagName === 'SELECT' ? '' : '';
      });
    }
    document.getElementById('modal-customer').classList.remove('hide');
  }

  function healthValue() {
    var ids = Array.prototype.slice.call(arguments);
    for (var i = 0; i < ids.length; i += 1) {
      var el = document.getElementById(ids[i]);
      if (el) return el.value || null;
    }
    return null;
  }

  function healthRadioValue(name) {
    var checked = document.querySelector('input[name="' + name + '"]:checked');
    return checked ? checked.value : null;
  }

  function healthCheckboxValues(name) {
    return Array.prototype.slice.call(document.querySelectorAll('input[name="' + name + '"]:checked')).map(function (el) {
      return el.value;
    });
  }

  function renderHealthDetail(data) {
    var box = document.getElementById('health-detail');
    if (!box) return;
    if (!data || !data.id) {
      box.style.display = 'none';
      box.innerHTML = '';
      selectedHealthDetailId = '';
      return;
    }
    selectedHealthDetailId = String(data.id);
    var rows = [
      ['客户', data.customer_name], ['日期', data.assessment_date], ['填表人', data.assessor], ['年龄', data.age],
      ['身高(cm)', data.height_cm], ['体重(kg)', data.weight_kg], ['地址', data.address], ['既往史', data.past_medical_history],
      ['家族史', data.family_history], ['过敏史', data.allergy_history], ['过敏详情', data.allergy_details], ['吸烟情况', data.smoking_status],
      ['烟龄', data.smoking_years], ['支/日', data.cigarettes_per_day], ['饮酒情况', data.drinking_status], ['饮酒年限', data.drinking_years],
      ['近一月疲劳', data.fatigue_last_month], ['睡眠状况', data.sleep_quality], ['睡眠时长', data.sleep_hours], ['近半年血压', data.blood_pressure_test],
      ['近半年血脂', data.blood_lipid_test], ['慢性疼痛', data.chronic_pain], ['疼痛描述', data.pain_details],
      ['运动方式', (data.exercise_methods || []).join('、')], ['每周锻炼频次', data.weekly_exercise_freq],
      ['健康需求', (data.health_needs || []).join('、')], ['备注', data.notes]
    ];
    box.innerHTML = '<h3 style="margin-top:0">档案详细信息</h3>' + rows.map(function (row) {
      return '<div><strong>' + escapeHtml(row[0]) + '：</strong>' + escapeHtml(row[1] || '-') + '</div>';
    }).join('');
    box.style.display = 'block';
    box.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function loadHealthPage() {
    initHealthCustomerPicker();
    var q = (document.getElementById('health-search').value || '').trim();
    get('/api/health-assessments' + (q ? '?search=' + encodeURIComponent(q) : '')).then(function (list) {
      var tbody = document.getElementById('health-list');
      tbody.innerHTML = toList(list).map(function (h) {
        return '<tr><td>' + (h.customer_name || '') + '</td><td>' + (h.assessment_date || '') + '</td><td>' + (h.height_cm || '-') + '</td><td>' + (h.weight_kg || '-') + '</td><td>' + (h.fatigue_last_month || '-') + '</td><td>' + (h.sleep_quality || '-') + '</td><td>' + (h.weekly_exercise_freq || '-') + '</td><td>' + (h.past_medical_history || '-') + '</td><td><button class="btn btn-small btn-secondary" data-health-detail="' + h.id + '">详细信息</button> <button class="btn btn-small btn-primary" data-health-edit="' + h.id + '">编辑</button></td></tr>';
      }).join('');
      tbody.querySelectorAll('[data-health-detail]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          get('/api/health-assessments/' + btn.dataset.healthDetail).then(function (data) {
            renderHealthDetail(data || {});
          });
        });
      });
      tbody.querySelectorAll('[data-health-edit]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          get('/api/health-assessments/' + btn.dataset.healthEdit).then(function (data) {
            editingHealthSnapshot = data && data.id ? JSON.parse(JSON.stringify(data)) : null;
            setHealthEditMode(!!(data && data.id));
            fillHealthForm(data || {});
          });
        });
      });
      if (selectedHealthDetailId) {
        var exists = toList(list).some(function (item) { return String(item.id) === selectedHealthDetailId; });
        if (exists) {
          get('/api/health-assessments/' + selectedHealthDetailId).then(function (data) {
            renderHealthDetail(data || {});
          });
        } else {
          renderHealthDetail(null);
        }
      }
    });
  }


  function setAppointmentEditMode(record) {
    var bar = document.getElementById('apt-edit-actions');
    if (record && record.id) {
      appointmentEditId = record.id;
      if (bar) bar.classList.remove('hide');
      document.getElementById('btn-apt-save').textContent = '保存修改';
      document.getElementById('btn-apt-mark-cancel').textContent = '改为取消预约';
    } else {
      appointmentEditId = null;
      if (bar) bar.classList.add('hide');
      document.getElementById('btn-apt-save').textContent = '保存预约';
    }
  }

  function fillAppointmentEquipmentByProject() {
    var projectId = document.getElementById('apt-project').value;
    var sel = document.getElementById('apt-equipment');
    var project = appointmentProjects.find(function (p) { return String(p.id) === String(projectId); });
    var requiredName = project ? projectEquipmentMap[project.name] : '';
    var options = appointmentEquipment.filter(function (e) {
      return !requiredName || e.name === requiredName;
    });
    sel.innerHTML = '<option value="">请选择设备</option>' + options.map(function (e) { return '<option value="' + e.id + '">' + e.name + '</option>'; }).join('');
  }

  function renderAppointmentTimeSelectors() {
    var startSel = document.getElementById('apt-start');
    var endSel = document.getElementById('apt-end');
    var selectedStart = startSel.value;
    var selectedEnd = endSel.value;
    var startOptions = [];
    var endOptions = [];
    appointmentSlots.forEach(function (slot) {
      if (startOptions.indexOf(slot.start_time) < 0) startOptions.push(slot.start_time);
      if (endOptions.indexOf(slot.end_time) < 0) endOptions.push(slot.end_time);
    });
    startSel.innerHTML = '<option value="">请选择开始时间</option>' + startOptions.map(function (t) { return '<option value="' + t + '">' + t + '</option>'; }).join('');
    endSel.innerHTML = '<option value="">请选择结束时间</option>' + endOptions.map(function (t) { return '<option value="' + t + '">' + t + '</option>'; }).join('');
    if (selectedStart) startSel.value = selectedStart;
    if (selectedEnd) endSel.value = selectedEnd;
  }

  function applyTimeSelection() {
    var start = document.getElementById('apt-start').value;
    var end = document.getElementById('apt-end').value;
    if (!start || !end) return;
    var matched = appointmentSlots.some(function (slot) {
      return slot.start_time === start && slot.end_time === end;
    });
    if (!matched) {
      showMsg('apt-msg', '开始和结束时间需为同一可预约时段', true);
      return;
    }
    showMsg('apt-msg', '');
  }

  function setHomeAppointmentEditMode(record) {
    var bar = document.getElementById('home-edit-actions');
    if (record && record.id) {
      homeAppointmentEditId = record.id;
      document.getElementById('btn-home-save').textContent = '保存修改';
      if (bar) bar.classList.remove('hide');
    } else {
      homeAppointmentEditId = null;
      document.getElementById('btn-home-save').textContent = '保存上门预约';
      if (bar) bar.classList.add('hide');
    }
  }

  function getStatusMeta(status) {
    if (status === 'cancelled') {
      return { text: '取消预约', cls: 'status-pill-cancelled', editable: false };
    }
    return { text: '预约成功！', cls: 'status-pill-success', editable: true };
  }

  function renderStatusPill(status) {
    var meta = getStatusMeta(status);
    return '<span class="status-pill ' + meta.cls + '">' + meta.text + '</span>';
  }

  function renderOperationTime(record) {
    return record.updated_at || record.created_at || '-';
  }

  function loadAppointmentsPage() {
    setAppointmentEditMode(null);
    appointmentSlots = [];
    renderAppointmentTimeSelectors();
    fillCustomerSelect('apt-customer');
    Promise.all([fillProjectSelect('apt-project', true), fillEquipmentSelect('apt-equipment')]).then(function () {
      fillAppointmentEquipmentByProject();
    });
    fillStaffSelect('apt-staff');
    var sortBy = (document.getElementById('apt-sort') || {}).value || 'time_desc';
    get('/api/appointments?sort_by=' + encodeURIComponent(sortBy)).then(function (list) {
      var tbody = document.getElementById('apt-list');
      tbody.innerHTML = toList(list).map(function (a) {
        var meta = getStatusMeta(a.status);
        var action = meta.editable
          ? '<button class="btn btn-small btn-secondary" data-apt-edit="' + a.id + '">编辑</button>'
          : '';
        return '<tr><td>' + (a.customer_name || '') + '</td><td>' + (a.project_name || '-') + '</td><td>' + (a.equipment_name || '-') + '</td><td>' + (a.staff_name || '-') + '</td><td>' + (a.appointment_date || '') + '</td><td>' + (a.start_time || '') + '~' + (a.end_time || '') + '</td><td>' + renderStatusPill(a.status) + '</td><td>' + action + '</td><td>' + renderOperationTime(a) + '</td></tr>';
      }).join('');
      tbody.querySelectorAll('[data-apt-edit]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          var item = toList(list).find(function (x) { return String(x.id) === String(btn.dataset.aptEdit); });
          if (!item) return;
          setAppointmentEditMode(item);
          document.getElementById('apt-customer').value = item.customer_id || '';
          document.getElementById('apt-project').value = item.project_id || '';
          fillAppointmentEquipmentByProject();
          document.getElementById('apt-equipment').value = item.equipment_id || '';
          document.getElementById('apt-staff').value = item.staff_id || '';
          document.getElementById('apt-date').value = item.appointment_date || '';
          document.getElementById('apt-notes').value = item.notes || '';
          document.getElementById('apt-start').value = item.start_time || '';
          document.getElementById('apt-end').value = item.end_time || '';
          checkAppointmentAvailability();
        });
      });
    });
  }

  function checkAppointmentAvailability() {
    var date = document.getElementById('apt-date').value;
    var projectId = document.getElementById('apt-project').value;
    var equipmentId = document.getElementById('apt-equipment').value;
    if (!date || !projectId) {
      document.getElementById('apt-availability').textContent = '请先选择日期和项目';
      return;
    }
    get('/api/appointments/free-slots?date=' + encodeURIComponent(date) + '&project_id=' + encodeURIComponent(projectId)).then(function (res) {
      if (res.error) { document.getElementById('apt-availability').textContent = res.error; return; }
      var rows = toList(res).filter(function (s) {
        if (!equipmentId) return (s.available_equipment || []).length > 0;
        return (s.available_equipment || []).some(function (e) { return String(e.id) === String(equipmentId); });
      });
      appointmentSlots = rows;
      renderAppointmentTimeSelectors();
      document.getElementById('apt-availability').innerHTML = rows.map(function (s) {
        var names = (s.available_equipment || []).map(function (e) { return e.name; }).join('、') || '无可用设备';
        return '<div>' + s.start_time + '-' + s.end_time + '：可用设备 ' + names + '；可用人员 ' + (s.available_staff_count || 0) + '</div>';
      }).join('');
      if (appointmentEditId) {
        var keepStart = document.getElementById('apt-start').value;
        var keepEnd = document.getElementById('apt-end').value;
        var keepMatched = rows.some(function (r) { return r.start_time === keepStart && r.end_time === keepEnd; });
        if (!keepMatched) {
          document.getElementById('apt-start').value = '';
          document.getElementById('apt-end').value = '';
        }
      }
      applyTimeSelection();
    });
  }

  function loadHomeAppointmentsPage() {
    setHomeAppointmentEditMode(null);
    fillCustomerSelect('home-customer');
    fillProjectSelect('home-project', true, 'home').then(function () {
      var projectSel = document.getElementById('home-project');
      var allowNames = ['上门康复护理', '中医养生咨询', '康复训练指导', '血糖测试', '按摩'];
      var options = Array.prototype.slice.call(projectSel.options || []);
      var hasPlaceholder = options.length && !options[0].value;
      var kept = options.filter(function (opt) { return hasPlaceholder && !opt.value ? true : allowNames.indexOf(opt.text) >= 0; });
      if (!kept.length || kept[0].value) kept.unshift(new Option('请选择项目', ''));
      projectSel.innerHTML = '';
      kept.forEach(function (opt) { projectSel.appendChild(opt); });
    });
    fillStaffSelect('home-staff');
    var sortBy = (document.getElementById('home-sort') || {}).value || 'time_desc';
    get('/api/home-appointments?sort_by=' + encodeURIComponent(sortBy)).then(function (list) {
      var rows = toList(list);
      var tbody = document.getElementById('home-list');
      tbody.innerHTML = rows.map(function (a) {
        var meta = getStatusMeta(a.status);
        var action = meta.editable
          ? '<button class="btn btn-small btn-secondary" data-home-edit="' + a.id + '">编辑</button>'
          : '';
        return '<tr><td>' + (a.customer_name || '') + '</td><td>' + (a.project_name || '-') + '</td><td>' + (a.appointment_date || '') + '</td><td>' + (a.start_time || '') + '~' + (a.end_time || '') + '</td><td>' + (a.location || '-') + '</td><td>' + (a.staff_name || '-') + '</td><td>' + renderStatusPill(a.status) + '</td><td>' + action + '</td><td>' + renderOperationTime(a) + '</td></tr>';
      }).join('');
      tbody.querySelectorAll('[data-home-edit]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          var item = rows.find(function (x) { return String(x.id) === String(btn.dataset.homeEdit); });
          if (!item) return;
          setHomeAppointmentEditMode(item);
          document.getElementById('home-customer').value = item.customer_id || '';
          document.getElementById('home-project').value = item.project_id || '';
          document.getElementById('home-staff').value = item.staff_id || '';
          document.getElementById('home-date').value = item.appointment_date || '';
          document.getElementById('home-start').value = item.start_time || '';
          document.getElementById('home-end').value = item.end_time || '';
          document.getElementById('home-location').value = item.location || '';
          document.getElementById('home-contact-person').value = item.contact_person || '';
          document.getElementById('home-contact-phone').value = item.contact_phone || '';
          document.getElementById('home-notes').value = item.notes || '';
        });
      });
    });
  }

  function loadUsagePage() {
    get('/api/equipment-usage/service-stats').then(function (res) {
      if (res.error) { showMsg('usage-msg', res.error, true); return; }
      renderUsagePopularity(toList(res.items), res.total || 0);
    });
  }

  function renderUsagePopularity(items, total) {
    var tbody = document.getElementById('usage-list');
    var chart = document.getElementById('usage-popularity-chart');
    if (!tbody || !chart) return;
    if (!items.length) {
      chart.innerHTML = '<p style="color:#666">暂无预约服务数据</p>';
      tbody.innerHTML = '<tr><td colspan="4">暂无数据</td></tr>';
      return;
    }
    var max = Math.max.apply(null, items.map(function (x) { return x.appointment_count || 0; }).concat([1]));
    chart.innerHTML = items.map(function (x, idx) {
      var count = x.appointment_count || 0;
      var pct = Math.round((count / max) * 100);
      return '<div class="trend-bar"><div class="date">TOP' + (idx + 1) + ' ' + (x.project_name || '未命名项目') + '</div><div class="bar"><span style="width:' + pct + '%"></span></div><div class="value">' + count + '</div></div>';
    }).join('');
    tbody.innerHTML = items.map(function (x, idx) {
      var count = x.appointment_count || 0;
      var ratio = total ? ((count * 100 / total).toFixed(1) + '%') : '0%';
      return '<tr><td>' + (idx + 1) + '</td><td>' + (x.project_name || '-') + '</td><td>' + count + '</td><td>' + ratio + '</td></tr>';
    }).join('');
    showMsg('usage-msg', '已自动统计预约服务共 ' + total + ' 条记录，当前最受欢迎项目：' + (items[0].project_name || '-'));
  }

  function loadSurveysPage() {
    fillCustomerSelect('survey-customer');
    fillProjectSelect('survey-project', true, 'home');
  }

  function loadPortraitPage() {
    get('/api/dashboard/health-portrait').then(function (res) {
      if (res.error) {
        showMsg('portrait-msg', res.error, true);
        return;
      }
      var d1 = res.dimension1 || {};
      var d2 = res.dimension2 || {};
      var d3 = res.dimension3 || {};
      showMsg('portrait-msg', '已基于最新健康档案生成画像，共覆盖客户 ' + (res.total_customers || 0) + ' 人');
      renderKpiCards('portrait-kpi-cards', [
        { name: '总人数', value: (d1.cards || {}).total_people || 0 },
        { name: 'BMI异常率', value: ((d1.cards || {}).bmi_abnormal_rate || 0) + '%' },
        { name: '66岁以上占比', value: ((d1.cards || {}).senior_ratio || 0) + '%' }
      ]);
      renderCircleChart('portrait-gender-pie', toList(d1.gender_distribution), false);
      renderLegend('portrait-gender-legend', toList(d1.gender_distribution));
      renderHorizontalBars('portrait-age-bars', toList(d1.age_distribution), '#27ae60');
      renderCircleChart('portrait-bmi-pie', toList(d1.bmi_distribution), false);
      renderLegend('portrait-bmi-legend', toList(d1.bmi_distribution));
      renderTagCloud('portrait-tag-cloud', toList(d1.tag_cloud));

      renderCircleChart('portrait-risk-donut', toList(d2.risk_distribution), true);
      renderLegend('portrait-risk-legend', toList(d2.risk_distribution));
      renderHorizontalBars('portrait-disease-top10', toList(d2.past_history_top10), '#8e44ad');
      renderHorizontalBars('portrait-family-top10', toList(d2.family_history_top10), '#c0392b');
      renderHighRiskTable('portrait-high-risk-list', toList(d2.high_risk_customers));

      renderKpiCards('portrait-habit-kpi', [
        { name: '吸烟占比', value: (d3.smoking_ratio || 0) + '%' },
        { name: '饮酒占比', value: (d3.drinking_ratio || 0) + '%' },
        { name: '睡眠异常占比', value: (d3.sleep_abnormal_ratio || 0) + '%' },
        { name: '低运动+不良习惯', value: d3.low_exercise_bad_habit_people || 0 }
      ]);
      renderHorizontalBars('portrait-exercise-top10', toList(d3.exercise_top10), '#16a085');
      renderHorizontalBars('portrait-needs-top10', toList(d3.health_needs_top10), '#2980b9');
      renderHorizontalBars('portrait-heatmap', toList(d3.behavior_heatmap), '#f39c12');
    });
  }

  function renderKpiCards(elId, items) {
    var box = document.getElementById(elId);
    if (!box) return;
    var list = toList(items);
    if (!list.length) {
      box.innerHTML = '<div style="color:#666">暂无数据</div>';
      return;
    }
    box.innerHTML = list.map(function (x) {
      return '<div class="kpi-card"><div class="k">' + (x.name || '-') + '</div><div class="v">' + (x.value == null ? '-' : x.value) + '</div></div>';
    }).join('');
  }

  function renderTagCloud(elId, items) {
    var box = document.getElementById(elId);
    if (!box) return;
    var list = toList(items);
    if (!list.length) {
      box.innerHTML = '<span style="color:#666">暂无标签</span>';
      return;
    }
    box.innerHTML = list.slice(0, 18).map(function (x) {
      return '<span class="tag-item">' + (x.name || '-') + ' · ' + (x.count || 0) + '</span>';
    }).join('');
  }

  function renderHighRiskTable(elId, items) {
    var tbody = document.getElementById(elId);
    if (!tbody) return;
    var list = toList(items);
    if (!list.length) {
      tbody.innerHTML = '<tr><td colspan="3">暂无数据</td></tr>';
      return;
    }
    tbody.innerHTML = list.slice(0, 12).map(function (x) {
      return '<tr><td>' + (x.customer_name || '-') + '</td><td>' + (x.risk_level || '-') + '</td><td>' + (x.warnings || '-') + '</td></tr>';
    }).join('');
  }

  function renderLegend(elId, list) {
    var box = document.getElementById(elId);
    if (!box) return;
    if (!list.length) {
      box.innerHTML = '<div>暂无数据</div>';
      return;
    }
    var total = list.reduce(function (sum, item) { return sum + (item.count || 0); }, 0) || 1;
    box.innerHTML = list.map(function (item, idx) {
      var color = chartColor(idx);
      var ratio = Math.round(((item.count || 0) * 100) / total);
      return '<div><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:' + color + ';margin-right:6px"></span>' + (item.name || '-') + '：' + (item.count || 0) + '（' + ratio + '%）</div>';
    }).join('');
  }

  function renderCircleChart(elId, list, donut) {
    var box = document.getElementById(elId);
    if (!box) return;
    if (!list.length) {
      box.innerHTML = '<p style="color:#666">暂无数据</p>';
      return;
    }
    var total = list.reduce(function (sum, item) { return sum + (item.count || 0); }, 0);
    if (!total) {
      box.innerHTML = '<p style="color:#666">暂无数据</p>';
      return;
    }
    var current = 0;
    var cx = 80;
    var cy = 80;
    var radius = 60;
    var innerRadius = donut ? 38 : 0;
    var paths = list.map(function (item, idx) {
      var value = item.count || 0;
      var start = current / total * Math.PI * 2;
      current += value;
      var end = current / total * Math.PI * 2;
      return piePath(cx, cy, radius, innerRadius, start, end, chartColor(idx));
    }).join('');
    box.innerHTML = '<svg class="' + (donut ? 'donut-svg' : 'pie-svg') + '" viewBox="0 0 160 160">' + paths + '</svg>';
  }

  function piePath(cx, cy, rOuter, rInner, start, end, color) {
    var x1 = cx + rOuter * Math.cos(start);
    var y1 = cy + rOuter * Math.sin(start);
    var x2 = cx + rOuter * Math.cos(end);
    var y2 = cy + rOuter * Math.sin(end);
    var largeArc = end - start > Math.PI ? 1 : 0;
    if (!rInner) {
      return '<path d="M ' + cx + ' ' + cy + ' L ' + x1 + ' ' + y1 + ' A ' + rOuter + ' ' + rOuter + ' 0 ' + largeArc + ' 1 ' + x2 + ' ' + y2 + ' Z" fill="' + color + '"></path>';
    }
    var x3 = cx + rInner * Math.cos(end);
    var y3 = cy + rInner * Math.sin(end);
    var x4 = cx + rInner * Math.cos(start);
    var y4 = cy + rInner * Math.sin(start);
    return '<path d="M ' + x1 + ' ' + y1 + ' A ' + rOuter + ' ' + rOuter + ' 0 ' + largeArc + ' 1 ' + x2 + ' ' + y2 + ' L ' + x3 + ' ' + y3 + ' A ' + rInner + ' ' + rInner + ' 0 ' + largeArc + ' 0 ' + x4 + ' ' + y4 + ' Z" fill="' + color + '"></path>';
  }

  function renderHorizontalBars(elId, list, color) {
    var box = document.getElementById(elId);
    if (!box) return;
    if (!list.length) {
      box.innerHTML = '<p style="color:#666">暂无数据</p>';
      return;
    }
    var max = Math.max.apply(null, list.map(function (x) { return x.count || 0; }).concat([1]));
    box.innerHTML = list.map(function (x) {
      var width = Math.round(((x.count || 0) * 100) / max);
      return '<div class="bar-row"><div class="label">' + (x.name || '-') + '</div><div class="bar-track"><div class="bar-fill" style="width:' + width + '%;background:' + color + '"></div></div><div class="value">' + (x.count || 0) + '</div></div>';
    }).join('');
  }

  function chartColor(idx) {
    var colors = ['#3498db', '#9b59b6', '#1abc9c', '#f39c12', '#e74c3c', '#2ecc71', '#34495e', '#16a085', '#8e44ad', '#d35400'];
    return colors[idx % colors.length];
  }

  document.querySelectorAll('.sidebar a').forEach(function (a) {
    a.addEventListener('click', function (e) { e.preventDefault(); showPage(a.dataset.page); });
  });
  var btnEquipmentRangeQuery = document.getElementById('btn-equipment-range-query');
  if (btnEquipmentRangeQuery) {
    btnEquipmentRangeQuery.addEventListener('click', function () {
      loadStats();
    });
  }

  document.getElementById('btn-customer-search').addEventListener('click', loadCustomers);
  document.getElementById('btn-customer-reset').addEventListener('click', function () {
    document.getElementById('customer-search').value = '';
    loadCustomers();
  });

  document.getElementById('btn-health-search').addEventListener('click', loadHealthPage);
  document.getElementById('btn-health-reset').addEventListener('click', function () {
    document.getElementById('health-search').value = '';
    loadHealthPage();
  });
  document.getElementById('health-customer-search').addEventListener('input', function (e) {
    renderHealthCustomerSelect(e.target.value);
  });
  document.getElementById('btn-health-cancel-edit').addEventListener('click', function () {
    if (editingHealthSnapshot && editingHealthSnapshot.id) {
      fillHealthForm(editingHealthSnapshot);
      showMsg('health-msg', '已退出编辑，原始记录未修改', false);
    } else {
      fillHealthForm({});
      showMsg('health-msg', '', false);
    }
    clearHealthEditState();
  });
  document.getElementById('btn-confirm-cancel').addEventListener('click', closeConfirmModal);
  document.getElementById('btn-confirm-submit').addEventListener('click', function () {
    if (typeof pendingAction === 'function') pendingAction();
  });
  document.getElementById('btn-customer-add').addEventListener('click', function () { openCustomerModal(null); });
  document.getElementById('btn-modal-cancel').addEventListener('click', function () { document.getElementById('modal-customer').classList.add('hide'); });
  document.getElementById('btn-modal-save').addEventListener('click', function () {
    var id = document.getElementById('modal-customer-id').value;
    var body = {
      name: document.getElementById('mc-name').value,
      id_card: document.getElementById('mc-id_card').value.trim(),
      phone: document.getElementById('mc-phone').value.trim(),
      address: document.getElementById('mc-address').value.trim(),
      gender: document.getElementById('mc-gender').value,
      birth_date: document.getElementById('mc-birth_date').value || null
    };
    if (!body.address) {
      showMsg('customer-msg', '地址为必填项', true);
      return;
    }
    if (body.id_card.length !== 18) {
      showMsg('customer-msg', '身份证号必须为18位', true);
      return;
    }
    if (!/^\d{11}$/.test(body.phone)) {
      showMsg('customer-msg', '手机号必须为11位数字', true);
      return;
    }

    if (!id) {
      post('/api/customers', body).then(function (res) {
        if (res.error) { showMsg('customer-msg', res.error, true); return; }
        document.getElementById('modal-customer').classList.add('hide');
        showMsg('customer-msg', res.message || '保存成功');
        loadCustomers();
      });
      return;
    }

    customerEditSnapshot = body;
    openConfirmModal('确认修改客户信息', [
      ['姓名', body.name],
      ['身份证', body.id_card],
      ['电话', body.phone],
      ['地址', body.address],
      ['性别', body.gender],
      ['出生日期', body.birth_date]
    ], function () {
      put('/api/customers/' + id, customerEditSnapshot).then(function (res) {
        if (res.error) { showMsg('customer-msg', res.error, true); return; }
        closeConfirmModal();
        document.getElementById('modal-customer').classList.add('hide');
        showMsg('customer-msg', res.message || '保存成功');
        loadCustomers();
      });
    });
  });

  document.getElementById('btn-health-save').addEventListener('click', function () {
    var cid = document.getElementById('health-customer').value;
    var hid = document.getElementById('health-id').value;
    if (!cid) { showMsg('health-msg', '请选择客户', true); return; }
    var body = {
      customer_id: parseInt(cid, 10),
      assessment_date: healthValue('health-date'),
      assessor: healthValue('ha-assessor'),
      age: healthValue('ha-age'),
      height_cm: healthValue('ha-height-cm', 'health-height'),
      weight_kg: healthValue('ha-weight-kg', 'health-weight'),
      address: healthValue('ha-address'),
      past_medical_history: healthValue('ha-past-medical-history', 'health-symptoms'),
      family_history: healthValue('ha-family-history', 'health-diagnosis'),
      allergy_history: healthRadioValue('ha-allergy-history'),
      allergy_details: healthValue('ha-allergy-details'),
      smoking_status: healthRadioValue('ha-smoking-status'),
      smoking_years: healthValue('ha-smoking-years'),
      cigarettes_per_day: healthValue('ha-cigarettes-per-day'),
      drinking_status: healthRadioValue('ha-drinking-status'),
      drinking_years: healthValue('ha-drinking-years'),
      fatigue_last_month: healthRadioValue('ha-fatigue-last-month'),
      sleep_quality: healthRadioValue('ha-sleep-quality'),
      sleep_hours: healthRadioValue('ha-sleep-hours'),
      blood_pressure_test: healthRadioValue('ha-blood-pressure-test'),
      blood_lipid_test: healthRadioValue('ha-blood-lipid-test'),
      chronic_pain: healthRadioValue('ha-chronic-pain'),
      pain_details: healthValue('ha-pain-details'),
      exercise_methods: healthCheckboxValues('health-exercise-method'),
      weekly_exercise_freq: healthRadioValue('ha-weekly-exercise-freq'),
      health_needs: healthCheckboxValues('health-need').concat(healthValue('ha-health-needs-other') ? ['其他:' + healthValue('ha-health-needs-other')] : []),
      notes: healthValue('ha-notes', 'health-notes')
    };

    if (!hid) {
      post('/api/health-assessments', body).then(function (res) {
        if (res.error) { showMsg('health-msg', res.error, true); return; }
        showMsg('health-msg', res.message);
        fillHealthForm({});
        clearHealthEditState();
        loadHealthPage();
      });
      return;
    }

    var confirmRows = [
      ['客户', selectedCustomerName()],
      ['日期', body.assessment_date],
      ['填表人', body.assessor],
      ['年龄', body.age],
      ['身高(cm)', body.height_cm],
      ['体重(kg)', body.weight_kg],
      ['地址', body.address],
      ['既往史', body.past_medical_history],
      ['家族史', body.family_history],
      ['过敏史', body.allergy_history],
      ['过敏详情', body.allergy_details],
      ['吸烟情况', body.smoking_status],
      ['烟龄', body.smoking_years],
      ['支/日', body.cigarettes_per_day],
      ['饮酒情况', body.drinking_status],
      ['饮酒年限', body.drinking_years],
      ['近一月疲劳', body.fatigue_last_month],
      ['睡眠状况', body.sleep_quality],
      ['睡眠时长', body.sleep_hours],
      ['近半年血压', body.blood_pressure_test],
      ['近半年血脂', body.blood_lipid_test],
      ['慢性疼痛', body.chronic_pain],
      ['疼痛描述', body.pain_details],
      ['运动方式', (body.exercise_methods || []).join('、')],
      ['锻炼频次', body.weekly_exercise_freq],
      ['健康需求', (body.health_needs || []).join('、')],
      ['备注', body.notes]
    ];

    openConfirmModal('请确认修改后的健康档案信息', confirmRows, function () {
      put('/api/health-assessments/' + hid, body).then(function (res) {
        if (res.error) { showMsg('health-msg', res.error, true); return; }
        closeConfirmModal();
        showMsg('health-msg', res.message);
        clearHealthEditState();
        loadHealthPage();
        get('/api/health-assessments/' + hid).then(function (data) {
          renderHealthDetail(data || {});
        });
      });
    });
  });

  document.getElementById('btn-apt-check').addEventListener('click', checkAppointmentAvailability);


  document.getElementById('apt-project').addEventListener('change', function () {
    fillAppointmentEquipmentByProject();
    checkAppointmentAvailability();
  });
  document.getElementById('apt-equipment').addEventListener('change', checkAppointmentAvailability);
  document.getElementById('apt-date').addEventListener('change', checkAppointmentAvailability);
  document.getElementById('apt-start').addEventListener('change', applyTimeSelection);
  document.getElementById('apt-end').addEventListener('change', applyTimeSelection);
  document.getElementById('apt-sort').addEventListener('change', loadAppointmentsPage);
  document.getElementById('btn-apt-cancel-edit').addEventListener('click', function () {
    setAppointmentEditMode(null);
    document.getElementById('apt-start').value = '';
    document.getElementById('apt-end').value = '';
    showMsg('apt-msg', '已退出编辑');
  });
  document.getElementById('btn-apt-mark-cancel').addEventListener('click', function () {
    if (!appointmentEditId) return;
    openConfirmModal('确认修改预约状态', [['状态', '取消预约']], function () {
      post('/api/appointments/' + appointmentEditId + '/cancel', {}).then(function (res) {
        if (res.error) { showMsg('apt-msg', res.error, true); return; }
        closeConfirmModal();
        showMsg('apt-msg', '修改成功');
        loadAppointmentsPage();
      });
    });
  });

  document.getElementById('btn-apt-save').addEventListener('click', function () {
    var body = {
      customer_id: document.getElementById('apt-customer').value,
      project_id: document.getElementById('apt-project').value,
      equipment_id: document.getElementById('apt-equipment').value,
      staff_id: document.getElementById('apt-staff').value,
      appointment_date: document.getElementById('apt-date').value,
      start_time: document.getElementById('apt-start').value,
      end_time: document.getElementById('apt-end').value,
      notes: document.getElementById('apt-notes').value,
      status: 'scheduled'
    };
    if (!body.customer_id || !body.project_id || !body.appointment_date || !body.start_time || !body.end_time || !body.equipment_id) {
      showMsg('apt-msg', '请填写必填项', true);
      return;
    }
    if (isPastDate(body.appointment_date)) {
      showMsg('apt-msg', '预约时间仅可选择当天及以后日期', true);
      return;
    }
    var rows = [
      ['客户', document.getElementById('apt-customer').selectedOptions[0] ? document.getElementById('apt-customer').selectedOptions[0].text : ''],
      ['项目', document.getElementById('apt-project').selectedOptions[0] ? document.getElementById('apt-project').selectedOptions[0].text : ''],
      ['设备', document.getElementById('apt-equipment').selectedOptions[0] ? document.getElementById('apt-equipment').selectedOptions[0].text : ''],
      ['人员', document.getElementById('apt-staff').selectedOptions[0] ? document.getElementById('apt-staff').selectedOptions[0].text : ''],
      ['预约时间', body.appointment_date + ' ' + body.start_time + '-' + body.end_time]
    ];
    openConfirmModal(appointmentEditId ? '确认修改预约后保存记录' : '确认预约信息', rows, function () {
      var req = appointmentEditId ? put('/api/appointments/' + appointmentEditId, body) : post('/api/appointments', body);
      req.then(function (res) {
        if (res.error) { showMsg('apt-msg', res.error, true); return; }
        closeConfirmModal();
        showMsg('apt-msg', appointmentEditId ? '预约修改成功' : res.message);
        loadAppointmentsPage();
      });
    });
  });


  document.getElementById('btn-home-save').addEventListener('click', function () {
    var body = {
      customer_id: document.getElementById('home-customer').value,
      project_id: document.getElementById('home-project').value,
      staff_id: document.getElementById('home-staff').value,
      appointment_date: document.getElementById('home-date').value,
      start_time: document.getElementById('home-start').value,
      end_time: document.getElementById('home-end').value,
      location: document.getElementById('home-location').value,
      contact_person: document.getElementById('home-contact-person').value,
      contact_phone: document.getElementById('home-contact-phone').value,
      notes: document.getElementById('home-notes').value,
      status: 'scheduled'
    };
    if (!body.customer_id || !body.project_id || !body.appointment_date || !body.start_time || !body.end_time || !body.location) {
      showMsg('home-msg', '请填写必填项', true); return;
    }
    if (body.start_time < '08:30' || body.end_time > '16:00' || body.start_time >= body.end_time) {
      showMsg('home-msg', '上门预约时间需在08:30-16:00且结束时间晚于开始时间', true); return;
    }
    var rows = [
      ['客户', document.getElementById('home-customer').selectedOptions[0] ? document.getElementById('home-customer').selectedOptions[0].text : ''],
      ['项目', document.getElementById('home-project').selectedOptions[0] ? document.getElementById('home-project').selectedOptions[0].text : ''],
      ['人员', document.getElementById('home-staff').selectedOptions[0] ? document.getElementById('home-staff').selectedOptions[0].text : ''],
      ['预约时间', body.appointment_date + ' ' + body.start_time + '-' + body.end_time],
      ['地点', body.location]
    ];
    openConfirmModal(homeAppointmentEditId ? '确认修改预约后保存记录' : '确认上门预约信息', rows, function () {
      var req = homeAppointmentEditId ? put('/api/home-appointments/' + homeAppointmentEditId, body) : post('/api/home-appointments', body);
      req.then(function (res) {
        if (res.error) { showMsg('home-msg', res.error, true); return; }
        closeConfirmModal();
        showMsg('home-msg', homeAppointmentEditId ? '上门预约修改成功' : res.message);
        loadHomeAppointmentsPage();
      });
    });
  });

  document.getElementById('btn-home-cancel-edit').addEventListener('click', function () {
    setHomeAppointmentEditMode(null);
    ['home-start', 'home-end', 'home-location', 'home-contact-person', 'home-contact-phone', 'home-notes'].forEach(function (id) {
      document.getElementById(id).value = '';
    });
    showMsg('home-msg', '已退出编辑');
  });
  document.getElementById('home-sort').addEventListener('change', loadHomeAppointmentsPage);

  document.getElementById('btn-home-mark-cancel').addEventListener('click', function () {
    if (!homeAppointmentEditId) return;
    openConfirmModal('确认修改预约状态', [['状态', '取消预约']], function () {
      post('/api/home-appointments/' + homeAppointmentEditId + '/cancel', {}).then(function (res) {
        if (res.error) { showMsg('home-msg', res.error, true); return; }
        closeConfirmModal();
        showMsg('home-msg', '修改成功');
        loadHomeAppointmentsPage();
      });
    });
  });


  document.getElementById('btn-survey-save').addEventListener('click', function () {
    var cid = document.getElementById('survey-customer').value;
    if (!cid) { showMsg('survey-msg', '请选择客户', true); return; }
    var surveyProject = document.getElementById('survey-project');
    if (!surveyProject || !surveyProject.value) { showMsg('survey-msg', '请选择反馈项目', true); return; }
    var body = {
      customer_id: parseInt(cid, 10),
      service_rating: document.getElementById('survey-service').value || 5,
      equipment_rating: document.getElementById('survey-equipment').value || 5,
      environment_rating: document.getElementById('survey-env').value || 5,
      staff_rating: document.getElementById('survey-staff').value || 5,
      service_project: (document.getElementById('survey-project').selectedOptions[0] || {}).text || '',
      feedback: document.getElementById('survey-feedback').value,
      suggestions: document.getElementById('survey-feedback').value
    };
    post('/api/satisfaction-surveys', body).then(function (res) {
      if (res.error) { showMsg('survey-msg', res.error, true); return; }
      showMsg('survey-msg', res.message);
    });
  });

  function refreshQueryExportScope() {
    var scope = document.getElementById('qe-scope').value;
    var customerSel = document.getElementById('qe-customer');
    var customerLabel = document.getElementById('qe-customer-label');
    var hideCustomer = scope === 'all';
    customerSel.style.display = hideCustomer ? 'none' : 'inline-flex';
    customerLabel.style.display = hideCustomer ? 'none' : 'inline-flex';
  }

  document.getElementById('qe-scope').addEventListener('change', refreshQueryExportScope);

  document.getElementById('btn-query-export-download').addEventListener('click', function () {
    var scope = document.getElementById('qe-scope').value;
    var dataset = document.getElementById('qe-dataset').value;
    var customerId = document.getElementById('qe-customer').value;
    if (scope === 'single' && !customerId) {
      showMsg('query-export-msg', '请选择要下载的客户', true);
      return;
    }
    var url = '/api/export/query-download?scope=' + encodeURIComponent(scope) + '&dataset=' + encodeURIComponent(dataset);
    if (scope === 'single') url += '&customer_id=' + encodeURIComponent(customerId);
    get(url).then(function (res) {
      if (res.error) {
        showMsg('query-export-msg', res.error, true);
        return;
      }
      if (res.download_url) window.location.href = res.download_url;
      showMsg('query-export-msg', '已触发下载：' + (res.filename || ''));
    });
  });


  document.getElementById('btn-backup-path-select').addEventListener('click', function () {
    post('/api/system/backup-path/select', {}).then(function (res) {
      if (!res || res.error) {
        showMsg('query-export-msg', (res && res.error) || '暂时无法打开本地路径选择框，请手动输入路径', true);
        return;
      }
      document.getElementById('backup-path').value = res.backup_directory || '';
      showMsg('query-export-msg', '已选择备份路径：' + (res.backup_directory || ''));
    });
  });

  document.getElementById('btn-backup-path-save').addEventListener('click', function () {
    var backupPath = (document.getElementById('backup-path').value || '').trim();
    if (!backupPath) {
      showMsg('query-export-msg', '请先输入数据库备份路径', true);
      return;
    }
    post('/api/system/backup-path', { backup_directory: backupPath }).then(function (res) {
      if (res.error) { showMsg('query-export-msg', res.error, true); return; }
      document.getElementById('backup-path').value = res.backup_directory || backupPath;
      showMsg('query-export-msg', '备份路径已保存：' + (res.backup_directory || backupPath));
    });
  });

  document.getElementById('btn-backup-now').addEventListener('click', function () {
    var backupPath = (document.getElementById('backup-path').value || '').trim();
    post('/api/system/backup', { backup_directory: backupPath }).then(function (res) {
      if (res.error || res.status === 'failed') { showMsg('query-export-msg', res.message || res.error || '备份失败', true); return; }
      if (res.backup_file) {
        showMsg('query-export-msg', '备份成功：' + res.backup_file);
      } else {
        showMsg('query-export-msg', '备份成功：' + (res.filename || ''));
      }
      if (backupPath) document.getElementById('backup-path').value = backupPath;
    });
  });

  document.getElementById('btn-search').addEventListener('click', function () {
    var q = document.getElementById('search-q').value.trim();
    var type = document.getElementById('search-type').value;
    var url = '/api/search?type=' + type + (q ? '&q=' + encodeURIComponent(q) : '');
    get(url).then(function (data) {
      var html = '';
      var labels = { customers: '客户信息', health_records: '健康档案', appointments: '预约记录', equipment_usage: '仪器使用', surveys: '满意度' };
      var cols = {
        customers: ['name', 'id_card', 'phone', 'address'],
        health_records: ['customer_name', 'record_date', 'height_cm', 'weight_kg', 'blood_pressure', 'symptoms', 'diagnosis'],
        appointments: ['customer_name', 'equipment_name', 'appointment_date', 'start_time', 'end_time', 'status'],
        equipment_usage: ['customer_name', 'equipment_name', 'usage_date', 'duration_minutes', 'operator'],
        surveys: ['customer_name', 'service_project', 'service_rating', 'equipment_rating', 'environment_rating', 'staff_rating', 'feedback', 'survey_date']
      };
      Object.keys(labels).forEach(function (key) {
        var arr = data[key];
        if (!arr || !arr.length) return;
        html += '<div class="result-section"><h3>' + labels[key] + ' (' + arr.length + ')</h3><table><thead><tr>';
        var c = cols[key] || Object.keys(arr[0] || {});
        c.forEach(function (k) { html += '<th>' + k + '</th>'; });
        html += '</tr></thead><tbody>';
        arr.forEach(function (row) {
          html += '<tr>';
          c.forEach(function (k) { html += '<td>' + (row[k] != null ? row[k] : '') + '</td>'; });
          html += '</tr>';
        });
        html += '</tbody></table></div>';
      });
      document.getElementById('search-result').innerHTML = html || '<p style="color:#666">无结果</p>';
    });
  });



  function loginSystem() {
    var username = (document.getElementById('login-username').value || '').trim();
    var password = (document.getElementById('login-password').value || '').trim();
    if (!username || !password) { showMsg('login-msg', '请输入账号和密码', true); return; }
    post('/api/auth/login', { username: username, password: password }).then(function (res) {
      if (res.error) { showMsg('login-msg', res.error, true); return; }
      document.getElementById('login-screen').classList.add('hide');
      document.getElementById('app-shell').classList.remove('hide');
      showPage('home');
    });
  }

  document.getElementById('btn-login').addEventListener('click', loginSystem);
  document.getElementById('login-password').addEventListener('keydown', function (e) {
    if (e.key === 'Enter') loginSystem();
  });

  var today = new Date().toISOString().slice(0, 10);
  document.getElementById('health-date').value = today;
  document.getElementById('apt-date').value = today;
  document.getElementById('apt-date').setAttribute('min', today);
  document.getElementById('home-date').value = today;
  refreshQueryExportScope();

  function fillHealthForm(data) {
    document.querySelectorAll('input[name^="ha-"]').forEach(function (el) { if (el.type === 'radio') el.checked = false; });
    document.querySelectorAll('input[name="health-exercise-method"], input[name="health-need"]').forEach(function (el) { el.checked = false; });
    document.getElementById('health-id').value = data.id || '';
    if (data.customer_name && !document.getElementById('health-customer-search').value) {
      document.getElementById('health-customer-search').value = data.customer_name;
      renderHealthCustomerSelect(data.customer_name);
    }
    document.getElementById('health-customer').value = data.customer_id || '';
    document.getElementById('health-date').value = (data.assessment_date || today || '').slice(0, 10);
    document.getElementById('ha-assessor').value = data.assessor || '';
    document.getElementById('ha-age').value = data.age || '';
    document.getElementById('ha-height-cm').value = data.height_cm || '';
    document.getElementById('ha-weight-kg').value = data.weight_kg || '';
    document.getElementById('ha-address').value = data.address || '';
    document.getElementById('ha-past-medical-history').value = data.past_medical_history || '';
    document.getElementById('ha-family-history').value = data.family_history || '';
    document.getElementById('ha-allergy-details').value = data.allergy_details || '';
    document.getElementById('ha-smoking-years').value = data.smoking_years || '';
    document.getElementById('ha-cigarettes-per-day').value = data.cigarettes_per_day || '';
    document.getElementById('ha-drinking-years').value = data.drinking_years || '';
    document.getElementById('ha-pain-details').value = data.pain_details || '';
    document.getElementById('ha-health-needs-other').value = (data.health_needs || []).filter(function(x){return x.indexOf('其他:')===0;}).map(function(x){return x.replace('其他:','');})[0] || '';
    document.getElementById('ha-notes').value = data.notes || '';

    var radios = ['ha-allergy-history', 'ha-smoking-status', 'ha-drinking-status', 'ha-fatigue-last-month', 'ha-sleep-quality', 'ha-sleep-hours', 'ha-blood-pressure-test', 'ha-blood-lipid-test', 'ha-chronic-pain', 'ha-weekly-exercise-freq'];
    radios.forEach(function(name) {
      var val = data[name.replace('ha-', '').replace(/-/g, '_')];
      if (name === 'ha-weekly-exercise-freq') val = data.weekly_exercise_freq;
      var el = document.querySelector('input[name="' + name + '"][value="' + val + '"]');
      if (el) el.checked = true;
    });

    var checkGroups = { 'health-exercise-method': data.exercise_methods, 'health-need': data.health_needs };
    Object.keys(checkGroups).forEach(function(name) {
      var vals = checkGroups[name] || [];
      document.querySelectorAll('input[name="' + name + '"]').forEach(function(el) {
        el.checked = vals.indexOf(el.value) !== -1;
      });
    });
    window.scrollTo(0, 0);
    showMsg('health-msg', '', false);
  }

})();
