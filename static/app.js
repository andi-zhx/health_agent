(function () {
  const API = '';
  function parseJsonResponse(r) {
    return r.text().then(function (text) {
      if (!text) return {};
      try {
        return JSON.parse(text);
      } catch (e) {
        var fallback = '服务返回异常，请刷新后重试';
        if (typeof text === 'string') {
          if (text.indexOf('<!doctype html') >= 0 || text.indexOf('<html') >= 0) {
            return { error: '服务端发生异常，请稍后重试' };
          }
          var shortText = text.trim();
          if (shortText) fallback = shortText.slice(0, 120);
        }
        return { error: fallback };
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
        var normalized = data;
        if (data && typeof data === 'object' && Object.prototype.hasOwnProperty.call(data, 'success')) {
          normalized = data.success ? (data.data == null ? {} : data.data) : { error: data.message || '请求失败', error_code: data.error_code || 'UNKNOWN_ERROR' };
        }
        if (response.status === 401 && url !== '/api/auth/login') {
          showLoginScreen((normalized && normalized.error) || (data && data.message) || '未登录或登录已失效，请重新登录');
        }
        if (!response.ok && normalized && !normalized.error) {
          normalized.error = '请求失败(' + response.status + ')';
        }
        return normalized;
      });
    }).catch(function () {
      return { error: '网络请求失败，请稍后重试' };
    });
  }

  function get(url) { return requestJson(url); }
  function post(url, body) { return requestJson(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }); }
  function put(url, body) { return requestJson(url, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }); }

  function toList(data) {
    if (data && Array.isArray(data.items)) return data.items;
    return Array.isArray(data) ? data : [];
  }

  function getPagination(data) {
    return (data && data.pagination) || {};
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
    if (name === 'query-export') loadQueryExportPage();
  }

  function loadQueryExportPage() {
    fillCustomerSelect('qe-customer');
    get('/api/system/backup-path').then(function (res) {
      if (!res || res.error) return;
      document.getElementById('backup-path').value = res.backup_directory || '';
    });
    loadBackupList();
  }

  function loadBackupList() {
    var sel = document.getElementById('restore-backup-file');
    if (!sel) return;
    get('/api/system/backups').then(function (rows) {
      var list = toList(rows).filter(function (row) {
        return row && row.status === 'success' && row.backup_file;
      });
      sel.innerHTML = '<option value="">请选择备份文件</option>' + list.map(function (row) {
        var name = row.backup_file || row.backup_time || '';
        var time = row.backup_time ? ('（' + row.backup_time + '）') : '';
        return '<option value="' + name + '">' + name + time + '</option>';
      }).join('');
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
    }).catch(function () {
      document.getElementById('appointment-trend').innerHTML = '<p style="color:#666">暂无数据</p>';
      document.getElementById('equipment-usage-top').innerHTML = '<tr><td colspan="3">暂无数据</td></tr>';
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
    box.textContent = '军休所-静安所';
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

  function fillCustomerSelect(selId) {
    get('/api/customers?page=1&page_size=500&sort_by=name_asc').then(function (list) {
      var sel = document.getElementById(selId);
      if (sel) {
        var old = sel.value;
        sel.innerHTML = '<option value="">请选择客户</option>' + toList(list).map(function (c) { return '<option value="' + c.id + '">' + c.name + ' ' + (c.phone || '') + '</option>'; }).join('');
        if (old) sel.value = old;
      }
      if (selId === 'apt-customer') {
        appointmentCustomerList = toList(list);
        renderAppointmentCustomerOptions('');
      }
      if (selId === 'home-customer') {
        homeCustomerList = toList(list);
        renderHomeCustomerOptions((document.getElementById('home-customer-search') || {}).value || '');
      }
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
        projects = projects.filter(function (p) { return APPOINTMENT_PROJECT_NAMES.indexOf(p.name) !== -1; });
      }
      if (selId === 'apt-project') appointmentProjects = projects;
      sel.innerHTML = '<option value="">请选择项目</option>' + projects.map(function (p) { return '<option value="' + p.id + '">' + p.name + '</option>'; }).join('');
      if (old) sel.value = old;
      if (selId === 'home-project' && sel.value) loadHomeSlotPanel(false);
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
  var appointmentSlotPanel = null;
  var selectedAppointmentSlot = null;
  var selectedAppointmentEquipmentId = '';
  var selectedAppointmentSlots = [];
  var appointmentCustomerList = [];
  var homeCustomerList = [];
  var homeAppointmentEditId = null;
  var homeSlotPanel = [];
  var homeStaffPanel = null;
  var selectedHomeSlot = null;
  var selectedHomeSlots = [];
  var appointmentProjects = [];
  var healthCustomerList = [];
  var listState = {
    customers: { page: 1, page_size: 20 },
    health: { page: 1, page_size: 20 },
    appointments: { page: 1, page_size: 20 },
    homeAppointments: { page: 1, page_size: 20 }
  };
  var APPOINTMENT_PROJECT_NAMES = ['听力测试', '艾灸', '高压氧仓', '磁疗', '红外理疗'];

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function selectedCustomerName() {
    var cid = String(document.getElementById('health-customer').value || '');
    var customer = healthCustomerList.find(function (c) { return String(c.id) === cid; });
    return customer ? ((customer.name || '') + (customer.phone ? (' ' + customer.phone) : '')) : '';
  }

  function renderHealthCustomerSelect(keyword) {
    var optionBox = document.getElementById('health-customer-options');
    if (!optionBox) return;
    var q = String(keyword || '').trim();
    var matched = healthCustomerList.filter(function (c) {
      var name = String(c.name || '');
      var phone = String(c.phone || '');
      return !q || name.indexOf(q) !== -1 || phone.indexOf(q) !== -1;
    });
    optionBox.innerHTML = matched.map(function (c) {
      var label = (c.name || '') + (c.phone ? ('（' + c.phone + '）') : '');
      return '<option value="' + escapeHtml(label) + '"></option>';
    }).join('');
  }

  function applySelectedCustomerByInput() {
    var input = document.getElementById('health-customer-search');
    var hidden = document.getElementById('health-customer');
    if (!input || !hidden) return;
    var raw = String(input.value || '').trim();
    if (!raw) {
      hidden.value = '';
      document.getElementById('ha-age').value = '';
      document.getElementById('ha-address').value = '';
      return;
    }
    var normalized = raw.replace(/[（）]/g, function (x) { return x === '（' ? '(' : ')'; });
    hidden.value = '';
    var exact = healthCustomerList.find(function (c) {
      var label = (c.name || '') + (c.phone ? ('(' + c.phone + ')') : '');
      return label === normalized || (c.name || '') === raw || (c.phone || '') === raw;
    });
    if (!exact) return;
    hidden.value = exact.id;
    input.value = (exact.name || '') + (exact.phone ? ('（' + exact.phone + '）') : '');
    document.getElementById('ha-age').value = exact.age || '';
    document.getElementById('ha-address').value = exact.address || '';
  }

  function initHealthCustomerPicker() {
    get('/api/customers?page=1&page_size=500&sort_by=name_asc').then(function (list) {
      healthCustomerList = toList(list);
      var searchInput = document.getElementById('health-customer-search');
      renderHealthCustomerSelect(searchInput ? searchInput.value : '');
      applySelectedCustomerByInput();
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

  function openHistoryModal(title, rows) {
    document.getElementById('modal-history-title').textContent = title;
    if (!rows.length) {
      document.getElementById('modal-history-content').innerHTML = '<div style="color:#666">暂无业务历史日志</div>';
    } else {
      document.getElementById('modal-history-content').innerHTML = rows.map(function (row) {
        return [
          '<div style="border:1px solid #e5e7eb;border-radius:8px;padding:10px 12px;margin-bottom:10px">',
          '<div><strong>创建时间：</strong>' + escapeHtml(row.created_at || '-') + '</div>',
          '<div><strong>修改时间：</strong>' + escapeHtml(row.modified_time || '-') + '</div>',
          '<div><strong>取消时间：</strong>' + escapeHtml(row.cancelled_time || '-') + '</div>',
          '<div><strong>操作人：</strong>' + escapeHtml(row.operator || '-') + '</div>',
          '<div><strong>变更前内容：</strong>' + escapeHtml(row.before_content || '-') + '</div>',
          '<div><strong>变更后内容：</strong>' + escapeHtml(row.after_content || '-') + '</div>',
          '</div>'
        ].join('');
      }).join('');
    }
    document.getElementById('modal-history').classList.remove('hide');
  }

  function closeHistoryModal() {
    document.getElementById('modal-history').classList.add('hide');
  }

  function viewBusinessHistory(module, targetId, title) {
    get('/api/business-history/' + module + '/' + targetId).then(function (res) {
      if (res && res.error) {
        showMsg(module === 'appointments' ? 'apt-msg' : 'home-msg', res.error, true);
        return;
      }
      openHistoryModal(title, toList(res));
    });
  }

  function loadCustomers() {
    var q = document.getElementById('customer-search').value;
    var qs = [
      'page=' + listState.customers.page,
      'page_size=' + listState.customers.page_size,
      'sort_by=created_desc'
    ];
    if (q) qs.push('search=' + encodeURIComponent(q));
    get('/api/customers?' + qs.join('&')).then(function (list) {
      var tbody = document.getElementById('customer-list');
      tbody.innerHTML = toList(list).map(function (c) {
        var createdAt = c.created_at ? String(c.created_at).replace('T', ' ').slice(0, 19) : '-';
        return '<tr><td>' + (c.name || '') + '</td><td>' + (c.age == null ? '-' : c.age) + '</td><td>' + (c.identity_type || '-') + '</td><td>' + (c.phone || '') + '</td><td>' + createdAt + '</td><td><button class="btn btn-small btn-primary" data-edit="' + c.id + '">编辑</button></td></tr>';
      }).join('');
      var p = getPagination(list);
      showMsg('customer-msg', '共 ' + (p.total || 0) + ' 条，当前第 ' + (p.page || 1) + ' / ' + (p.total_pages || 1) + ' 页');
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
        document.getElementById('mc-age').value = c.age == null ? '' : c.age;
        document.getElementById('mc-gender').value = c.gender || '';
        document.getElementById('mc-birth_date').value = (c.birth_date || '').slice(0, 10);
        var identity = String(c.identity_type || '').trim();
        document.getElementById('mc-identity-self').checked = identity === '本人';
        document.getElementById('mc-identity-family').checked = identity === '家属';
        document.getElementById('mc-military_rank').value = c.military_rank || '';
        document.getElementById('mc-id_card').value = c.id_card || '';
        document.getElementById('mc-phone').value = c.phone || '';
        document.getElementById('mc-address').value = c.address || '';
        document.getElementById('mc-record_creator').value = c.record_creator || '';
      });
    } else {
      ['mc-name', 'mc-age', 'mc-gender', 'mc-birth_date', 'mc-id_card', 'mc-phone', 'mc-address', 'mc-military_rank', 'mc-record_creator'].forEach(function (k) {
        var e = document.getElementById(k);
        if (e) e.value = e.tagName === 'SELECT' ? '' : '';
      });
      document.getElementById('mc-identity-self').checked = false;
      document.getElementById('mc-identity-family').checked = false;
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
      ['客户', data.customer_name], ['年龄', data.age],
      ['身高(cm)', data.height_cm], ['体重(kg)', data.weight_kg], ['地址', data.address], ['既往病史', data.past_medical_history],
      ['家族慢性病史', data.family_history], ['过敏史', data.allergy_history], ['过敏详情', data.allergy_details], ['吸烟情况', data.smoking_status],
      ['烟龄', data.smoking_years], ['饮酒情况', data.drinking_status], ['饮酒年限', data.drinking_years],
      ['睡眠状况', data.sleep_quality], ['睡眠时长', data.sleep_hours], ['近半年症状', data.recent_symptoms], ['详细情况', data.recent_symptom_detail],
      ['最影响生活的问题', data.life_impact_issues], ['近半年血压', data.blood_pressure_test],
      ['近半年血脂', data.blood_lipid_test], ['近半年血糖', data.blood_sugar_test],
      ['运动方式', (data.exercise_methods || []).join('、')], ['健康需求', (data.health_needs || []).join('、')], ['特殊情况', data.notes]
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
    var qs = [
      'page=' + listState.health.page,
      'page_size=' + listState.health.page_size,
      'sort_by=date_desc'
    ];
    if (q) qs.push('search=' + encodeURIComponent(q));
    get('/api/health-assessments?' + qs.join('&')).then(function (list) {
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
      var p = getPagination(list);
      showMsg('health-msg', '共 ' + (p.total || 0) + ' 条，当前第 ' + (p.page || 1) + ' / ' + (p.total_pages || 1) + ' 页');
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

  function resetAppointmentSlotSelection() {
    selectedAppointmentSlot = null;
    selectedAppointmentEquipmentId = '';
    selectedAppointmentSlots = [];
    renderEquipmentOptions();
  }

  function resetAppointmentForm() {
    document.getElementById('apt-customer').value = '';
    document.getElementById('apt-customer-search').value = '';
    document.getElementById('apt-project').value = '';
    document.getElementById('apt-date').value = today;
    document.getElementById('apt-notes').value = '';
    resetAppointmentSlotSelection();
    appointmentSlotPanel = null;
    renderAppointmentSlotPanel();
  }

  function renderAppointmentCustomerOptions(keyword) {
    var optionBox = document.getElementById('apt-customer-options');
    if (!optionBox) return;
    var q = String(keyword || '').trim();
    var matched = appointmentCustomerList.filter(function (c) {
      var name = String(c.name || '');
      var phone = String(c.phone || '');
      return !q || name.indexOf(q) !== -1 || phone.indexOf(q) !== -1;
    });
    optionBox.innerHTML = matched.map(function (c) {
      var label = (c.name || '') + (c.phone ? ('（' + c.phone + '）') : '');
      return '<option value="' + escapeHtml(label) + '"></option>';
    }).join('');
  }

  function applyAppointmentCustomerByInput() {
    var input = document.getElementById('apt-customer-search');
    var hidden = document.getElementById('apt-customer');
    if (!input || !hidden) return;
    var raw = String(input.value || '').trim();
    if (!raw) {
      hidden.value = '';
      return;
    }
    var normalized = raw.replace(/[（）]/g, function (x) { return x === '（' ? '(' : ')'; });
    hidden.value = '';
    var exact = appointmentCustomerList.find(function (c) {
      var label = (c.name || '') + (c.phone ? ('(' + c.phone + ')') : '');
      return label === normalized || (c.name || '') === raw || (c.phone || '') === raw;
    });
    if (!exact) return;
    hidden.value = exact.id;
    input.value = (exact.name || '') + (exact.phone ? ('（' + exact.phone + '）') : '');
  }

  function renderEquipmentOptions() {
    var slotHint = document.getElementById('apt-selected-slot');
    var box = document.getElementById('apt-equipment-options');
    if (!box || !slotHint) return;
    if (!selectedAppointmentSlots.length) {
      slotHint.textContent = '请先选择可预约时间段';
      box.innerHTML = '';
      return;
    }
    slotHint.textContent = '已选时间段：' + selectedAppointmentSlots.map(function (slot) {
      return slot.start_time + '-' + slot.end_time + '（设备' + (slot.equipment_label || '-') + '）';
    }).join('；');
    if (!selectedAppointmentSlot) {
      box.innerHTML = '<div class="appointment-tip">请点击已选中的时间段后选择设备</div>';
      return;
    }
    var equipmentList = selectedAppointmentSlot.available_equipment || [];
    if (!equipmentList.length) {
      box.innerHTML = '<div class="appointment-tip">该时间段暂无可选设备</div>';
      return;
    }
    box.innerHTML = equipmentList.map(function (item) {
      var active = String(selectedAppointmentEquipmentId) === String(item.id);
      var model = String(item.model || '').trim() || String(item.name || '').slice(-2);
      return '<label class="equipment-item ' + (active ? 'active' : '') + '">' +
        '<input type="radio" name="apt-equipment-radio" value="' + item.id + '" ' + (active ? 'checked' : '') + '>' +
        '<div><div class="name">' + escapeHtml(item.name || '-') + '</div><div class="detail">设备' + escapeHtml(model) + '</div></div>' +
        '</label>';
    }).join('');
    box.querySelectorAll('input[name="apt-equipment-radio"]').forEach(function (radio, idx) {
      radio.addEventListener('change', function () {
        var picked = equipmentList[idx];
        if (!picked) return;
        selectedAppointmentEquipmentId = String(picked.id);
        var slotIndex = selectedAppointmentSlots.findIndex(function (x) {
          return x.start_time === selectedAppointmentSlot.start_time && x.end_time === selectedAppointmentSlot.end_time;
        });
        if (slotIndex >= 0) {
          selectedAppointmentSlots[slotIndex].equipment_id = selectedAppointmentEquipmentId;
          selectedAppointmentSlots[slotIndex].equipment_name = selectedAppointmentEquipmentId ? (picked.name || '') : '';
          selectedAppointmentSlots[slotIndex].equipment_label = selectedAppointmentEquipmentId ? (picked.model || String(picked.name || '').slice(-2)) : '';
        }
        renderEquipmentOptions();
      });
    });
  }

  function renderAppointmentSlotPanel() {
    var slotsBox = document.getElementById('apt-slots');
    var tip = document.getElementById('apt-slot-tip');
    if (!slotsBox || !tip) return;
    var slots = (appointmentSlotPanel && appointmentSlotPanel.slots) || [];
    if (!slots.length) {
      slotsBox.innerHTML = '';
      tip.textContent = '请选择项目和日期后查看可预约时间';
      resetAppointmentSlotSelection();
      return;
    }
    tip.textContent = '可连续选择多个时间段（每次选中后在下方点设备，可再次点击取消该时间段）';
    slotsBox.innerHTML = slots.map(function (slot, idx) {
      var isAvailable = slot.status === 'available';
      var isSelected = selectedAppointmentSlots.some(function (x) { return x.start_time === slot.start_time && x.end_time === slot.end_time; });
      var cls = ['slot-card', isAvailable ? '' : 'full', isSelected ? 'selected' : ''].join(' ').trim();
      var meta = isAvailable ? ('可预约｜剩余设备 ' + (slot.available_equipment_count || 0) + ' 台') : '已约满';
      return '<div class="' + cls + '" data-slot-index="' + idx + '">' +
        '<div class="time">' + slot.start_time + ' - ' + slot.end_time + '</div>' +
        '<div class="meta">' + meta + '</div>' +
      '</div>';
    }).join('');
    slotsBox.querySelectorAll('[data-slot-index]').forEach(function (el) {
      el.addEventListener('click', function () {
        var idx = Number(this.getAttribute('data-slot-index'));
        var picked = slots[idx];
        if (!picked || picked.status !== 'available') return;
        var existed = selectedAppointmentSlots.findIndex(function (x) { return x.start_time === picked.start_time && x.end_time === picked.end_time; });
        if (existed >= 0) {
          var current = selectedAppointmentSlots[existed];
          var active = selectedAppointmentSlot && selectedAppointmentSlot.start_time === picked.start_time && selectedAppointmentSlot.end_time === picked.end_time;
          if (active) {
            selectedAppointmentSlots.splice(existed, 1);
            selectedAppointmentSlot = null;
            selectedAppointmentEquipmentId = '';
          } else {
            selectedAppointmentSlot = picked;
            selectedAppointmentEquipmentId = current.equipment_id ? String(current.equipment_id) : '';
          }
        } else {
          selectedAppointmentSlot = picked;
          selectedAppointmentEquipmentId = '';
          selectedAppointmentSlots.push({
            start_time: picked.start_time,
            end_time: picked.end_time,
            available_equipment: picked.available_equipment || [],
            equipment_id: '',
            equipment_name: '',
            equipment_label: '',
          });
        }
        renderAppointmentSlotPanel();
        renderEquipmentOptions();
      });
    });
  }

  function loadAppointmentSlotPanel(keepSelection) {
    var date = document.getElementById('apt-date').value;
    var projectId = document.getElementById('apt-project').value;
    if (!date || !projectId) {
      appointmentSlotPanel = null;
      renderAppointmentSlotPanel();
      return;
    }
    var query = '/api/appointments/slot-panel?date=' + encodeURIComponent(date) + '&project_id=' + encodeURIComponent(projectId);
    if (appointmentEditId) query += '&exclude_appointment_id=' + encodeURIComponent(appointmentEditId);
    get(query).then(function (res) {
      if (res.error) {
        appointmentSlotPanel = null;
        renderAppointmentSlotPanel();
        showMsg('apt-msg', res.error, true);
        return;
      }
      appointmentSlotPanel = res || { slots: [] };
      if (keepSelection && selectedAppointmentSlot) {
        var matched = (appointmentSlotPanel.slots || []).find(function (slot) {
          return slot.status === 'available' && slot.start_time === selectedAppointmentSlot.start_time && slot.end_time === selectedAppointmentSlot.end_time;
        });
        selectedAppointmentSlot = matched || null;
        if (!matched) selectedAppointmentEquipmentId = '';
      } else {
        resetAppointmentSlotSelection();
      }
      renderAppointmentSlotPanel();
      if (selectedAppointmentSlot) renderEquipmentOptions();
    });
  }

  function renderHomeCustomerOptions(keyword) {
    var optionBox = document.getElementById('home-customer-options');
    if (!optionBox) return;
    var q = String(keyword || '').trim();
    var matched = homeCustomerList.filter(function (c) {
      var name = String(c.name || '');
      var phone = String(c.phone || '');
      return !q || name.indexOf(q) !== -1 || phone.indexOf(q) !== -1;
    });
    optionBox.innerHTML = matched.map(function (c) {
      var label = (c.name || '') + (c.phone ? ('（' + c.phone + '）') : '');
      return '<option value="' + escapeHtml(label) + '"></option>';
    }).join('');
  }

  function applyHomeCustomerByInput() {
    var input = document.getElementById('home-customer-search');
    var hidden = document.getElementById('home-customer');
    if (!input || !hidden) return;
    var raw = String(input.value || '').trim();
    hidden.value = '';
    if (!raw) return;
    var normalized = raw.replace(/[（）]/g, function (x) { return x === '（' ? '(' : ')'; });
    var exact = homeCustomerList.find(function (c) {
      var label = (c.name || '') + (c.phone ? ('(' + c.phone + ')') : '');
      return label === normalized || (c.name || '') === raw || (c.phone || '') === raw;
    });
    if (!exact) return;
    hidden.value = exact.id;
    input.value = (exact.name || '') + (exact.phone ? ('（' + exact.phone + '）') : '');
  }

  function renderHomeSlotPanel() {
    var box = document.getElementById('home-slots');
    var tip = document.getElementById('home-slot-tip');
    if (!box || !tip) return;
    var slots = homeSlotPanel || [];
    if (!slots.length) {
      box.innerHTML = '';
      tip.textContent = '请选择项目和日期后查看可预约时间段（08:30-16:00，每30分钟）';
      return;
    }
    tip.textContent = '可连续选择多个时间段（可再次点击取消，服务人员按当前高亮时间段加载）';
    box.innerHTML = slots.map(function (slot, idx) {
      var available = (slot.available_count || 0) > 0;
      var selected = selectedHomeSlots.some(function (x) { return x.start_time === slot.start_time && x.end_time === slot.end_time; });
      var cls = ['slot-card', available ? '' : 'full', selected ? 'selected' : ''].join(' ').trim();
      var meta = available ? ('可预约｜空闲人员 ' + (slot.available_count || 0) + ' 人') : '已约满';
      return '<div class="' + cls + '" data-home-slot-index="' + idx + '"><div class="time">' + slot.start_time + ' - ' + slot.end_time + '</div><div class="meta">' + meta + '</div></div>';
    }).join('');
    box.querySelectorAll('[data-home-slot-index]').forEach(function (el) {
      el.addEventListener('click', function () {
        var idx = Number(this.getAttribute('data-home-slot-index'));
        var picked = slots[idx];
        if (!picked || (picked.available_count || 0) <= 0) return;
        var existed = selectedHomeSlots.findIndex(function (x) { return x.start_time === picked.start_time && x.end_time === picked.end_time; });
        if (existed >= 0) {
          var isActive = selectedHomeSlot && selectedHomeSlot.start_time === picked.start_time && selectedHomeSlot.end_time === picked.end_time;
          selectedHomeSlots.splice(existed, 1);
          if (isActive) selectedHomeSlot = null;
        } else {
          selectedHomeSlot = { start_time: picked.start_time, end_time: picked.end_time };
          selectedHomeSlots.push({ start_time: picked.start_time, end_time: picked.end_time });
        }
        if (!selectedHomeSlot && selectedHomeSlots.length) selectedHomeSlot = selectedHomeSlots[selectedHomeSlots.length - 1];
        if (selectedHomeSlot) {
          document.getElementById('home-start').value = selectedHomeSlot.start_time;
          document.getElementById('home-end').value = selectedHomeSlot.end_time;
        } else {
          document.getElementById('home-start').value = '';
          document.getElementById('home-end').value = '';
          document.getElementById('home-staff').value = '';
        }
        loadHomeStaffPanel();
        renderHomeSlotPanel();
      });
    });
  }

  function renderHomeStaffPanel() {
    var box = document.getElementById('home-staff-panel');
    var tip = document.getElementById('home-staff-tip');
    if (!box || !tip) return;
    var staff = (homeStaffPanel && homeStaffPanel.staff) || [];
    if (!selectedHomeSlot) {
      box.innerHTML = '';
      tip.textContent = '请先选择时间段';
      return;
    }
    if (!staff.length) {
      box.innerHTML = '';
      tip.textContent = '暂无可配置服务人员';
      return;
    }
    tip.textContent = '空闲服务人员 ' + (homeStaffPanel.available_count || 0) + ' 人';
    var selectedStaffId = String(document.getElementById('home-staff').value || '');
    box.innerHTML = staff.map(function (row) {
      var available = row.status === 'available';
      var selected = available && selectedStaffId && selectedStaffId === String(row.staff_id);
      var cls = ['home-staff-card', available ? '' : 'full', selected ? 'selected' : ''].join(' ').trim();
      return '<div class="' + cls + '" data-home-staff-id="' + row.staff_id + '" data-home-staff-status="' + row.status + '">' +
        '<div class="name">' + (row.staff_name || '-') + '</div><div class="meta">' + (row.role || '服务人员') + '｜' + (row.display || '') + '</div></div>';
    }).join('');
    box.querySelectorAll('[data-home-staff-id]').forEach(function (el) {
      el.addEventListener('click', function () {
        if (this.getAttribute('data-home-staff-status') !== 'available') return;
        document.getElementById('home-staff').value = this.getAttribute('data-home-staff-id');
        renderHomeStaffPanel();
      });
    });
  }

  function loadHomeSlotPanel(keepSelected) {
    applyHomeCustomerByInput();
    var date = (document.getElementById('home-date') || {}).value || '';
    var projectId = (document.getElementById('home-project') || {}).value || '';
    if (!date || !projectId) {
      homeSlotPanel = [];
      if (!keepSelected) {
        selectedHomeSlot = null;
        selectedHomeSlots = [];
      }
      renderHomeSlotPanel();
      renderHomeStaffPanel();
      return;
    }
    get('/api/home-appointments/slot-panel?date=' + encodeURIComponent(date) + '&project_id=' + encodeURIComponent(projectId)).then(function (res) {
      homeSlotPanel = (res && res.slots) || [];
      if (keepSelected && selectedHomeSlot) {
        selectedHomeSlots = selectedHomeSlots.filter(function (picked) {
          return homeSlotPanel.some(function (slot) {
            return slot.start_time === picked.start_time && slot.end_time === picked.end_time && (slot.available_count || 0) > 0;
          });
        });
        var matched = selectedHomeSlots.find(function (picked) {
          return picked.start_time === selectedHomeSlot.start_time && picked.end_time === selectedHomeSlot.end_time;
        });
        if (!matched && selectedHomeSlots.length) {
          selectedHomeSlot = selectedHomeSlots[selectedHomeSlots.length - 1];
          document.getElementById('home-start').value = selectedHomeSlot.start_time;
          document.getElementById('home-end').value = selectedHomeSlot.end_time;
        } else if (!matched) {
          selectedHomeSlot = null;
          selectedHomeSlots = [];
          document.getElementById('home-start').value = '';
          document.getElementById('home-end').value = '';
        }
      } else {
        selectedHomeSlot = null;
        selectedHomeSlots = [];
        document.getElementById('home-start').value = '';
        document.getElementById('home-end').value = '';
      }
      renderHomeSlotPanel();
      loadHomeStaffPanel();
    });
  }

  function loadHomeStaffPanel() {
    var date = (document.getElementById('home-date') || {}).value || '';
    var projectId = (document.getElementById('home-project') || {}).value || '';
    var start = (document.getElementById('home-start') || {}).value || '';
    var end = (document.getElementById('home-end') || {}).value || '';
    if (!date || !projectId || !start || !end) {
      homeStaffPanel = null;
      renderHomeStaffPanel();
      return;
    }
    var query = '/api/home-appointments/staff-panel?date=' + encodeURIComponent(date) +
      '&project_id=' + encodeURIComponent(projectId) +
      '&start_time=' + encodeURIComponent(start) +
      '&end_time=' + encodeURIComponent(end);
    get(query).then(function (res) {
      homeStaffPanel = res || { staff: [], available_count: 0 };
      var currentId = String(document.getElementById('home-staff').value || '');
      if (currentId) {
        var matched = (homeStaffPanel.staff || []).find(function (x) {
          return String(x.staff_id) === currentId && x.status === 'available';
        });
        if (!matched) document.getElementById('home-staff').value = '';
      }
      renderHomeStaffPanel();
    });
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

  function resetHomeAppointmentForm() {
    ['home-customer', 'home-project', 'home-start', 'home-end', 'home-staff', 'home-location', 'home-contact-person', 'home-contact-phone', 'home-notes'].forEach(function (id) {
      document.getElementById(id).value = '';
    });
    document.getElementById('home-customer-search').value = '';
    document.getElementById('home-date').value = today;
    homeSlotPanel = [];
    homeStaffPanel = null;
    selectedHomeSlot = null;
    selectedHomeSlots = [];
    renderHomeSlotPanel();
    renderHomeStaffPanel();
  }

  function getStatusMeta(status) {
    if (status === 'cancelled') {
      return { text: '取消预约', cls: 'status-pill-cancelled', editable: false };
    }
    return { text: '预约成功', cls: 'status-pill-success', editable: true };
  }

  function renderStatusPill(status) {
    var meta = getStatusMeta(status);
    return '<span class="status-pill ' + meta.cls + '">' + meta.text + '</span>';
  }

  function renderOperationTime(record) {
    return record.updated_at || record.created_at || '-';
  }

  function getCheckinMeta(checkinStatus, bookingStatus) {
    if (bookingStatus === 'cancelled') return { text: '-', cls: '' };
    if (checkinStatus === 'checked_in') return { text: '已签到', cls: 'checkin-btn-checked' };
    if (checkinStatus === 'no_show') return { text: '爽约', cls: 'checkin-btn-noshow' };
    return { text: '待签到', cls: 'checkin-btn-pending' };
  }

  function renderCheckinCell(record, moduleName) {
    var bookingStatus = String(record.status || '').toLowerCase();
    var checkinStatus = String(record.checkin_status || 'pending').toLowerCase();
    var meta = getCheckinMeta(checkinStatus, bookingStatus);
    if (bookingStatus === 'cancelled') return '<span>-</span>';
    var html = '<button class="checkin-btn ' + meta.cls + '" type="button" disabled>' + meta.text + '</button>';
    var canOperate = checkinStatus === 'pending' && String(record.appointment_date || '') === today;
    if (canOperate) {
      html += '<div class="checkin-cell-actions">' +
        '<button class="btn btn-small btn-primary" data-checkin-action="' + moduleName + '" data-checkin-id="' + record.id + '" data-checkin-target="checked_in">标记已签到</button>' +
        '<button class="btn btn-small btn-secondary" data-checkin-action="' + moduleName + '" data-checkin-id="' + record.id + '" data-checkin-target="no_show">标记爽约</button>' +
        '</div>';
    }
    return html;
  }

  function loadAppointmentsPage() {
    setAppointmentEditMode(null);
    appointmentSlotPanel = null;
    resetAppointmentSlotSelection();
    renderAppointmentSlotPanel();
    fillCustomerSelect('apt-customer');
    var aptCustomerInput = document.getElementById('apt-customer-search');
    if (aptCustomerInput) aptCustomerInput.value = '';
    fillProjectSelect('apt-project', true);
    var sortBy = (document.getElementById('apt-sort') || {}).value || 'time_desc';
    var qs = [
      'sort_by=' + encodeURIComponent(sortBy),
      'page=' + listState.appointments.page,
      'page_size=' + listState.appointments.page_size
    ];
    get('/api/appointments?' + qs.join('&')).then(function (list) {
      var tbody = document.getElementById('apt-list');
      tbody.innerHTML = toList(list).map(function (a) {
        var meta = getStatusMeta(a.status);
        var action = meta.editable
          ? '<button class="btn btn-small btn-secondary" data-apt-edit="' + a.id + '">编辑</button> <button class="btn btn-small btn-primary" data-apt-history="' + a.id + '">查看历史</button>'
          : '<button class="btn btn-small btn-primary" data-apt-history="' + a.id + '">查看历史</button>';
        return '<tr><td>' + (a.customer_name || '') + '</td><td>' + (a.project_name || '-') + '</td><td>' + (a.equipment_name || '-') + '</td><td>' + (a.appointment_date || '') + '</td><td>' + (a.start_time || '') + '~' + (a.end_time || '') + '</td><td>' + renderStatusPill(a.status) + '</td><td>' + renderCheckinCell(a, 'appointments') + '</td><td>' + action + '</td><td>' + renderOperationTime(a) + '</td></tr>';
      }).join('');
      var p = getPagination(list);
      showMsg('apt-msg', '共 ' + (p.total || 0) + ' 条，当前第 ' + (p.page || 1) + ' / ' + (p.total_pages || 1) + ' 页');
      tbody.querySelectorAll('[data-apt-edit]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          var item = toList(list).find(function (x) { return String(x.id) === String(btn.dataset.aptEdit); });
          if (!item) return;
          setAppointmentEditMode(item);
          document.getElementById('apt-customer').value = item.customer_id || '';
          var selectedCustomer = appointmentCustomerList.find(function (c) { return String(c.id) === String(item.customer_id); });
          document.getElementById('apt-customer-search').value = selectedCustomer ? ((selectedCustomer.name || '') + (selectedCustomer.phone ? ('（' + selectedCustomer.phone + '）') : '')) : '';
          document.getElementById('apt-project').value = item.project_id || '';
          document.getElementById('apt-date').value = item.appointment_date || '';
          document.getElementById('apt-notes').value = item.notes || '';
          selectedAppointmentSlot = { start_time: item.start_time || '', end_time: item.end_time || '' };
          selectedAppointmentEquipmentId = item.equipment_id || '';
          selectedAppointmentSlots = [{
            start_time: item.start_time || '',
            end_time: item.end_time || '',
            equipment_id: item.equipment_id || '',
            equipment_name: item.equipment_name || '',
            equipment_label: String(item.equipment_name || '').slice(-2),
          }];
          loadAppointmentSlotPanel(true);
        });
      });
      tbody.querySelectorAll('[data-apt-history]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          viewBusinessHistory('appointments', btn.dataset.aptHistory, '预约服务 - 业务历史日志');
        });
      });
      tbody.querySelectorAll('[data-checkin-action="appointments"]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          var target = btn.getAttribute('data-checkin-target');
          post('/api/appointments/' + btn.getAttribute('data-checkin-id') + '/checkin-status', { checkin_status: target }).then(function (res) {
            if (res.error) { showMsg('apt-msg', res.error, true); return; }
            showMsg('apt-msg', '签到状态已更新');
            loadAppointmentsPage();
          });
        });
      });
    });
  }

  function loadHomeAppointmentsPage() {
    setHomeAppointmentEditMode(null);
    fillCustomerSelect('home-customer');
    fillProjectSelect('home-project', true, 'home');
    homeSlotPanel = [];
    homeStaffPanel = null;
    selectedHomeSlot = null;
    selectedHomeSlots = [];
    document.getElementById('home-start').value = '';
    document.getElementById('home-end').value = '';
    document.getElementById('home-staff').value = '';
    renderHomeSlotPanel();
    renderHomeStaffPanel();
    var sortBy = (document.getElementById('home-sort') || {}).value || 'time_desc';
    var qs = [
      'sort_by=' + encodeURIComponent(sortBy),
      'page=' + listState.homeAppointments.page,
      'page_size=' + listState.homeAppointments.page_size
    ];
    get('/api/home-appointments?' + qs.join('&')).then(function (list) {
      var rows = toList(list);
      var tbody = document.getElementById('home-list');
      tbody.innerHTML = rows.map(function (a) {
        var meta = getStatusMeta(a.status);
        var action = meta.editable
          ? '<button class="btn btn-small btn-secondary" data-home-edit="' + a.id + '">编辑</button> <button class="btn btn-small btn-primary" data-home-history="' + a.id + '">查看历史</button>'
          : '<button class="btn btn-small btn-primary" data-home-history="' + a.id + '">查看历史</button>';
        return '<tr><td>' + (a.customer_name || '') + '</td><td>' + (a.project_name || '-') + '</td><td>' + (a.appointment_date || '') + '</td><td>' + (a.start_time || '') + '~' + (a.end_time || '') + '</td><td>' + (a.location || '-') + '</td><td>' + (a.staff_name || '-') + '</td><td>' + renderStatusPill(a.status) + '</td><td>' + renderCheckinCell(a, 'home_appointments') + '</td><td>' + action + '</td><td>' + renderOperationTime(a) + '</td></tr>';
      }).join('');
      var p = getPagination(list);
      showMsg('home-msg', '共 ' + (p.total || 0) + ' 条，当前第 ' + (p.page || 1) + ' / ' + (p.total_pages || 1) + ' 页');
      tbody.querySelectorAll('[data-home-edit]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          var item = rows.find(function (x) { return String(x.id) === String(btn.dataset.homeEdit); });
          if (!item) return;
          setHomeAppointmentEditMode(item);
          document.getElementById('home-customer').value = item.customer_id || '';
          var selectedCustomer = homeCustomerList.find(function (c) { return String(c.id) === String(item.customer_id); });
          document.getElementById('home-customer-search').value = selectedCustomer ? ((selectedCustomer.name || '') + (selectedCustomer.phone ? ('（' + selectedCustomer.phone + '）') : '')) : '';
          document.getElementById('home-project').value = item.project_id || '';
          document.getElementById('home-date').value = item.appointment_date || '';
          selectedHomeSlot = { start_time: item.start_time || '', end_time: item.end_time || '' };
          selectedHomeSlots = [{ start_time: item.start_time || '', end_time: item.end_time || '' }];
          document.getElementById('home-start').value = item.start_time || '';
          document.getElementById('home-end').value = item.end_time || '';
          document.getElementById('home-staff').value = item.staff_id || '';
          document.getElementById('home-location').value = item.location || '';
          document.getElementById('home-contact-person').value = item.contact_person || '';
          document.getElementById('home-contact-phone').value = item.contact_phone || '';
          document.getElementById('home-notes').value = item.notes || '';
          loadHomeSlotPanel(true);
        });
      });
      tbody.querySelectorAll('[data-home-history]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          viewBusinessHistory('home_appointments', btn.dataset.homeHistory, '上门预约 - 业务历史日志');
        });
      });
      tbody.querySelectorAll('[data-checkin-action="home_appointments"]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          var target = btn.getAttribute('data-checkin-target');
          post('/api/home-appointments/' + btn.getAttribute('data-checkin-id') + '/checkin-status', { checkin_status: target }).then(function (res) {
            if (res.error) { showMsg('home-msg', res.error, true); return; }
            showMsg('home-msg', '签到状态已更新');
            loadHomeAppointmentsPage();
          });
        });
      });
    });
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
      renderCircleChart('portrait-risk-donut', toList(d2.risk_distribution), true);
      renderLegend('portrait-risk-legend', toList(d2.risk_distribution));
      renderHorizontalBars('portrait-disease-top10', toList(d2.disease_top10), '#8e44ad');
      renderHorizontalBars('portrait-family-top10', toList(d2.family_history_top10), '#c0392b');

      renderKpiCards('portrait-habit-kpi', [
        { name: '吸烟占比', value: (d3.smoking_ratio || 0) + '%' },
        { name: '饮酒占比', value: (d3.drinking_ratio || 0) + '%' },
        { name: '睡眠异常占比', value: (d3.sleep_abnormal_ratio || 0) + '%' },
        { name: '低运动+不良习惯', value: d3.low_exercise_bad_habit_people || 0 }
      ]);
      renderHorizontalBars('portrait-exercise-top10', toList(d3.exercise_top10), '#16a085');
      renderHorizontalBars('portrait-needs-top10', toList(d3.health_needs_top10), '#2980b9');
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
    applySelectedCustomerByInput();
  });
  document.getElementById('health-customer-search').addEventListener('change', applySelectedCustomerByInput);
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
  document.getElementById('btn-history-close').addEventListener('click', closeHistoryModal);
  document.getElementById('btn-customer-add').addEventListener('click', function () { openCustomerModal(null); });
  document.getElementById('btn-modal-cancel').addEventListener('click', function () { document.getElementById('modal-customer').classList.add('hide'); });
  document.getElementById('btn-modal-save').addEventListener('click', function () {
    var id = document.getElementById('modal-customer-id').value;
    var identityType = '';
    if (document.getElementById('mc-identity-self').checked) identityType = '本人';
    if (document.getElementById('mc-identity-family').checked) identityType = '家属';
    var body = {
      name: document.getElementById('mc-name').value.trim(),
      gender: document.getElementById('mc-gender').value,
      age: document.getElementById('mc-age').value.trim(),
      birth_date: document.getElementById('mc-birth_date').value || null,
      identity_type: identityType,
      military_rank: document.getElementById('mc-military_rank').value.trim(),
      id_card: document.getElementById('mc-id_card').value.trim(),
      phone: document.getElementById('mc-phone').value.trim(),
      address: document.getElementById('mc-address').value.trim(),
      record_creator: document.getElementById('mc-record_creator').value.trim()
    };
    if (!body.name) {
      showMsg('customer-msg', '姓名为必填项', true);
      return;
    }
    if (!body.gender) {
      showMsg('customer-msg', '性别为必填项', true);
      return;
    }
    if (!/^\d+$/.test(body.age) || parseInt(body.age, 10) <= 0) {
      showMsg('customer-msg', '年龄为必填项，且必须为正整数', true);
      return;
    }
    if (!body.birth_date) {
      showMsg('customer-msg', '出生日期为必填项', true);
      return;
    }
    if (!body.identity_type) {
      showMsg('customer-msg', '身份为必选项，请选择“本人”或“家属”', true);
      return;
    }
    if (body.id_card && body.id_card.length !== 18) {
      showMsg('customer-msg', '身份证号为18位时才可保存', true);
      return;
    }
    if (!/^\d{11}$/.test(body.phone)) {
      showMsg('customer-msg', '手机号必须为11位数字', true);
      return;
    }
    if (!body.record_creator) {
      showMsg('customer-msg', '建档人为必填项', true);
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
      ['性别', body.gender],
      ['年龄', body.age],
      ['出生日期', body.birth_date],
      ['身份', body.identity_type],
      ['军级', body.military_rank],
      ['身份证', body.id_card],
      ['电话', body.phone],
      ['地址', body.address],
      ['建档人', body.record_creator]
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
    var lifeImpactIssues = healthCheckboxValues('ha-life-impact-issue');
    var lifeImpactIssueOther = healthValue('ha-life-impact-issue-other');
    var normalizedLifeImpactIssues = lifeImpactIssues.filter(function (item) { return item !== '其他'; });
    if (lifeImpactIssues.indexOf('其他') !== -1) {
      normalizedLifeImpactIssues.push(lifeImpactIssueOther ? ('其他:' + lifeImpactIssueOther) : '其他');
    }
    if (normalizedLifeImpactIssues.length > 3) {
      showMsg('health-msg', '最影响生活的问题最多选择3项', true);
      return;
    }
    var body = {
      customer_id: parseInt(cid, 10),
      assessment_date: healthValue('health-date'),
      assessor: null,
      age: healthValue('ha-age'),
      height_cm: healthValue('ha-height-cm', 'health-height'),
      weight_kg: healthValue('ha-weight-kg', 'health-weight'),
      address: healthValue('ha-address'),
      past_medical_history: healthCheckboxValues('ha-diagnosed-disease').concat(healthValue('ha-diagnosed-disease-other') ? ['其他:' + healthValue('ha-diagnosed-disease-other')] : []).join('、'),
      family_history: healthCheckboxValues('ha-family-disease').concat(healthValue('ha-family-disease-other') ? ['其他:' + healthValue('ha-family-disease-other')] : []).join('、'),
      allergy_history: healthRadioValue('ha-allergy-history'),
      allergy_details: healthValue('ha-allergy-details'),
      smoking_status: healthRadioValue('ha-smoking-status'),
      smoking_years: healthValue('ha-smoking-years'),
      cigarettes_per_day: null,
      drinking_status: healthRadioValue('ha-drinking-status'),
      drinking_years: healthValue('ha-drinking-years'),
      fatigue_last_month: null,
      sleep_quality: healthRadioValue('ha-sleep-quality'),
      sleep_hours: healthRadioValue('ha-sleep-hours'),
      recent_symptoms: healthCheckboxValues('ha-recent-symptom').concat(healthValue('ha-recent-symptom-other') ? ['其他:' + healthValue('ha-recent-symptom-other')] : []).join('、'),
      recent_symptom_detail: healthValue('ha-recent-symptom-detail'),
      life_impact_issues: normalizedLifeImpactIssues.join('、'),
      blood_pressure_test: healthRadioValue('ha-blood-pressure-test'),
      blood_lipid_test: healthRadioValue('ha-blood-lipid-test'),
      blood_sugar_test: healthRadioValue('ha-blood-sugar-test'),
      chronic_pain: null,
      pain_details: null,
      exercise_methods: healthCheckboxValues('health-exercise-method'),
      weekly_exercise_freq: null,
      health_needs: healthCheckboxValues('health-need').concat(healthValue('ha-health-needs-other') ? ['其他:' + healthValue('ha-health-needs-other')] : []),
      notes: healthCheckboxValues('ha-special-condition').join('、')
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
      ['年龄', body.age],
      ['身高(cm)', body.height_cm],
      ['体重(kg)', body.weight_kg],
      ['地址', body.address],
      ['既往病史', body.past_medical_history],
      ['家族慢性病史', body.family_history],
      ['过敏史', body.allergy_history],
      ['过敏详情', body.allergy_details],
      ['吸烟情况', body.smoking_status],
      ['烟龄', body.smoking_years],
      ['饮酒情况', body.drinking_status],
      ['饮酒年限', body.drinking_years],
      ['睡眠状况', body.sleep_quality],
      ['睡眠时长', body.sleep_hours],
      ['近半年症状', body.recent_symptoms],
      ['详细情况', body.recent_symptom_detail],
      ['最影响生活的问题', body.life_impact_issues],
      ['近半年血压', body.blood_pressure_test],
      ['近半年血脂', body.blood_lipid_test],
      ['近半年血糖', body.blood_sugar_test],
      ['运动方式', (body.exercise_methods || []).join('、')],
      ['健康需求', (body.health_needs || []).join('、')],
      ['特殊情况', body.notes]
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
  document.querySelectorAll('input[name="ha-life-impact-issue"]').forEach(function (el) {
    el.addEventListener('change', function () {
      var checked = healthCheckboxValues('ha-life-impact-issue');
      if (checked.length > 3) {
        this.checked = false;
        showMsg('health-msg', '最影响生活的问题最多选择3项', true);
      } else {
        showMsg('health-msg', '', false);
      }
    });
  });

  document.getElementById('apt-project').addEventListener('change', function () {
    loadAppointmentSlotPanel(false);
  });
  document.getElementById('apt-date').addEventListener('change', function () {
    loadAppointmentSlotPanel(false);
  });
  document.getElementById('apt-customer-search').addEventListener('input', function () {
    renderAppointmentCustomerOptions(this.value);
  });
  document.getElementById('apt-customer-search').addEventListener('change', function () {
    applyAppointmentCustomerByInput();
  });
  document.getElementById('apt-sort').addEventListener('change', loadAppointmentsPage);
  document.getElementById('btn-apt-cancel-edit').addEventListener('click', function () {
    setAppointmentEditMode(null);
    resetAppointmentSlotSelection();
    renderAppointmentSlotPanel();
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
    applyAppointmentCustomerByInput();
    var body = {
      customer_id: document.getElementById('apt-customer').value,
      project_id: document.getElementById('apt-project').value,
      appointment_date: document.getElementById('apt-date').value,
      notes: document.getElementById('apt-notes').value,
      status: 'scheduled'
    };
    if (!body.customer_id || !body.project_id || !body.appointment_date || !selectedAppointmentSlots.length) {
      showMsg('apt-msg', '请填写必填项', true);
      return;
    }
    if (selectedAppointmentSlots.some(function (slot) { return !slot.equipment_id; })) {
      showMsg('apt-msg', '请为每个已选时间段选择设备', true);
      return;
    }
    if (isPastDate(body.appointment_date)) {
      showMsg('apt-msg', '预约时间仅可选择当天及以后日期', true);
      return;
    }
    var firstEquipment = selectedAppointmentSlots[0].equipment_id;
    var allSameEquipment = selectedAppointmentSlots.every(function (slot) { return String(slot.equipment_id) === String(firstEquipment); });
    if (!allSameEquipment) {
      var confirmed = window.confirm('检测到连续时间段选择了不同设备，是否确认使用不同设备继续预约？');
      if (!confirmed) {
        showMsg('apt-msg', '请返回界面重新选择同一设备或调整时间段', true);
        return;
      }
    }
    selectedAppointmentSlots.sort(function (a, b) { return a.start_time.localeCompare(b.start_time); });
    var rows = [
      ['客户', document.getElementById('apt-customer-search').value || ''],
      ['项目', document.getElementById('apt-project').selectedOptions[0] ? document.getElementById('apt-project').selectedOptions[0].text : ''],
      ['时间段', selectedAppointmentSlots.map(function (slot) { return slot.start_time + '-' + slot.end_time; }).join('、')],
      ['设备', selectedAppointmentSlots.map(function (slot) { return slot.equipment_name || ('设备' + (slot.equipment_label || '-')); }).join('、')]
    ];
    openConfirmModal(appointmentEditId ? '确认修改预约后保存记录' : '确认预约信息', rows, function () {
      var requests = selectedAppointmentSlots.map(function (slot) {
        var payload = Object.assign({}, body, {
          equipment_id: slot.equipment_id,
          start_time: slot.start_time,
          end_time: slot.end_time
        });
        if (appointmentEditId) {
          return put('/api/appointments/' + appointmentEditId, payload);
        }
        return post('/api/appointments', payload);
      });
      Promise.all(requests).then(function (results) {
        var err = results.find(function (res) { return res && res.error; });
        if (err) { showMsg('apt-msg', err.error, true); return; }
        closeConfirmModal();
        showMsg('apt-msg', appointmentEditId ? '预约修改成功' : '预约成功，共保存 ' + results.length + ' 条记录');
        resetAppointmentForm();
        loadAppointmentsPage();
      });
    });
  });


  document.getElementById('btn-home-save').addEventListener('click', function () {
    applyHomeCustomerByInput();
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
    if (!body.customer_id || !body.project_id || !body.staff_id || !body.appointment_date || !body.location || !selectedHomeSlots.length) {
      showMsg('home-msg', '请填写必填项', true); return;
    }
    var invalidSlot = selectedHomeSlots.find(function (slot) {
      var startMinute = Number(String(slot.start_time || '').split(':')[1] || 0);
      var endMinute = Number(String(slot.end_time || '').split(':')[1] || 0);
      return slot.start_time < '08:30' || slot.end_time > '16:00' || slot.start_time >= slot.end_time || (startMinute !== 0 && startMinute !== 30) || (endMinute !== 0 && endMinute !== 30);
    });
    if (invalidSlot) {
      showMsg('home-msg', '上门预约时间段需在08:30-16:00且按30分钟选择', true); return;
    }
    selectedHomeSlots.sort(function (a, b) { return a.start_time.localeCompare(b.start_time); });
    var selectedCustomerText = document.getElementById('home-customer-search').value || '';
    var selectedStaff = (homeStaffPanel && homeStaffPanel.staff || []).find(function (s) { return String(s.staff_id) === String(body.staff_id); });
    var rows = [
      ['客户', selectedCustomerText],
      ['项目', document.getElementById('home-project').selectedOptions[0] ? document.getElementById('home-project').selectedOptions[0].text : ''],
      ['人员', selectedStaff ? selectedStaff.staff_name : ''],
      ['预约时间', body.appointment_date + ' ' + selectedHomeSlots.map(function (slot) { return slot.start_time + '-' + slot.end_time; }).join('、')],
      ['地点', body.location],
      ['联系人', body.contact_person || '-'],
      ['电话', body.contact_phone || '-']
    ];
    openConfirmModal(homeAppointmentEditId ? '确认修改预约后保存记录' : '确认上门预约信息', rows, function () {
      var requests = selectedHomeSlots.map(function (slot) {
        var payload = Object.assign({}, body, { start_time: slot.start_time, end_time: slot.end_time });
        if (homeAppointmentEditId) return put('/api/home-appointments/' + homeAppointmentEditId, payload);
        return post('/api/home-appointments', payload);
      });
      Promise.all(requests).then(function (results) {
        var err = results.find(function (res) { return res && res.error; });
        if (err) { showMsg('home-msg', err.error, true); return; }
        closeConfirmModal();
        showMsg('home-msg', homeAppointmentEditId ? '上门预约修改成功' : ('上门预约成功，共保存 ' + results.length + ' 条记录'));
        resetHomeAppointmentForm();
        loadHomeAppointmentsPage();
      });
    });
  });

  document.getElementById('btn-home-cancel-edit').addEventListener('click', function () {
    setHomeAppointmentEditMode(null);
    ['home-start', 'home-end', 'home-location', 'home-contact-person', 'home-contact-phone', 'home-notes', 'home-staff', 'home-customer'].forEach(function (id) {
      document.getElementById(id).value = '';
    });
    document.getElementById('home-customer-search').value = '';
    selectedHomeSlot = null;
    selectedHomeSlots = [];
    homeStaffPanel = null;
    renderHomeSlotPanel();
    renderHomeStaffPanel();
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
      loadBackupList();
    });
  });

  document.getElementById('btn-refresh-backups').addEventListener('click', function () {
    loadBackupList();
    showMsg('query-export-msg', '备份列表已刷新');
  });

  document.getElementById('btn-restore-backup').addEventListener('click', function () {
    var backupFile = (document.getElementById('restore-backup-file').value || '').trim();
    if (!backupFile) {
      showMsg('query-export-msg', '请先选择要恢复的备份文件', true);
      return;
    }
    var ok = window.confirm('恢复数据库会覆盖当前数据，是否继续？');
    if (!ok) return;
    post('/api/system/restore', { backup_file: backupFile }).then(function (res) {
      if (res.error || res.status === 'failed') {
        showMsg('query-export-msg', res.message || res.error || '恢复失败', true);
        return;
      }
      showMsg('query-export-msg', (res.message || '恢复成功') + '。请重启系统。');
    });
  });

  document.getElementById('btn-search').addEventListener('click', function () {
    var q = document.getElementById('search-q').value.trim();
    var type = document.getElementById('search-type').value;
    var url = '/api/search?type=' + type + (q ? '&q=' + encodeURIComponent(q) : '');
    get(url).then(function (data) {
      var html = '';
      var labels = { customers: '客户信息', health_records: '健康档案', appointments: '预约记录', visit_checkins: '来访登记' };
      var cols = {
        customers: ['name', 'id_card', 'phone', 'address'],
        health_records: ['customer_name', 'record_date', 'height_cm', 'weight_kg', 'blood_pressure', 'symptoms', 'diagnosis'],
        appointments: ['customer_name', 'equipment_name', 'appointment_date', 'start_time', 'end_time', 'status', 'checkin_status'],
        visit_checkins: ['customer_name', 'checkin_time', 'purpose', 'notes']
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
  document.getElementById('btn-toggle-login-password').addEventListener('click', function () {
    var pwdInput = document.getElementById('login-password');
    var currentType = pwdInput.getAttribute('type') || 'password';
    var nextType = currentType === 'password' ? 'text' : 'password';
    pwdInput.setAttribute('type', nextType);
    this.textContent = nextType === 'password' ? '显示' : '隐藏';
  });
  document.getElementById('login-password').addEventListener('keydown', function (e) {
    if (e.key === 'Enter') loginSystem();
  });

  var today = new Date().toISOString().slice(0, 10);
  document.getElementById('health-date').value = today;
  document.getElementById('apt-date').value = today;
  document.getElementById('apt-date').setAttribute('min', today);
  document.getElementById('home-date').value = today;
  document.getElementById('home-date').setAttribute('min', today);
  refreshQueryExportScope();

  document.getElementById('home-customer-search').addEventListener('input', function () {
    renderHomeCustomerOptions(this.value);
  });
  document.getElementById('home-customer-search').addEventListener('change', applyHomeCustomerByInput);
  document.getElementById('home-project').addEventListener('change', function () { loadHomeSlotPanel(false); });
  document.getElementById('home-date').addEventListener('change', function () { loadHomeSlotPanel(false); });

  function fillHealthForm(data) {
    document.querySelectorAll('input[name^="ha-"]').forEach(function (el) { if (el.type === 'radio') el.checked = false; });
    document.querySelectorAll('input[name="health-exercise-method"], input[name="health-need"], input[name="ha-diagnosed-disease"], input[name="ha-family-disease"], input[name="ha-special-condition"], input[name="ha-recent-symptom"], input[name="ha-life-impact-issue"]').forEach(function (el) { el.checked = false; });
    document.getElementById('health-id').value = data.id || '';
    if (data.customer_id) {
      var selected = healthCustomerList.find(function (c) { return String(c.id) === String(data.customer_id); });
      if (selected) {
        document.getElementById('health-customer-search').value = (selected.name || '') + (selected.phone ? ('（' + selected.phone + '）') : '');
      }
    } else if (data.customer_name && !document.getElementById('health-customer-search').value) {
      document.getElementById('health-customer-search').value = data.customer_name;
    } else if (!data.id) {
      document.getElementById('health-customer-search').value = '';
    }
    renderHealthCustomerSelect(document.getElementById('health-customer-search').value);
    document.getElementById('health-customer').value = data.customer_id || '';
    document.getElementById('health-date').value = (data.assessment_date || today || '').slice(0, 10);
    document.getElementById('ha-age').value = data.age || '';
    document.getElementById('ha-height-cm').value = data.height_cm || '';
    document.getElementById('ha-weight-kg').value = data.weight_kg || '';
    document.getElementById('ha-address').value = data.address || '';
    document.getElementById('ha-allergy-details').value = data.allergy_details || '';
    document.getElementById('ha-smoking-years').value = data.smoking_years || '';
    document.getElementById('ha-drinking-years').value = data.drinking_years || '';
    document.getElementById('ha-recent-symptom-other').value = '';
    document.getElementById('ha-recent-symptom-detail').value = data.recent_symptom_detail || '';
    document.getElementById('ha-life-impact-issue-other').value = '';
    document.getElementById('ha-health-needs-other').value = (data.health_needs || []).filter(function(x){return x.indexOf('其他:')===0;}).map(function(x){return x.replace('其他:','');})[0] || '';

    var radios = ['ha-allergy-history', 'ha-smoking-status', 'ha-drinking-status', 'ha-sleep-quality', 'ha-sleep-hours', 'ha-blood-pressure-test', 'ha-blood-lipid-test', 'ha-blood-sugar-test'];
    radios.forEach(function(name) {
      var val = data[name.replace('ha-', '').replace(/-/g, '_')];
      var el = document.querySelector('input[name="' + name + '"][value="' + val + '"]');
      if (el) el.checked = true;
    });

    var pastItems = String(data.past_medical_history || '').split('、').filter(Boolean);
    var familyItems = String(data.family_history || '').split('、').filter(Boolean);
    var symptomItems = String(data.recent_symptoms || '').split('、').filter(Boolean);
    var symptomOther = symptomItems.filter(function(x){ return x.indexOf('其他:')===0; }).map(function(x){ return x.replace('其他:',''); })[0] || '';
    var diagnosedOther = pastItems.filter(function(x){ return x.indexOf('其他:')===0; }).map(function(x){ return x.replace('其他:',''); })[0] || '';
    var familyOther = familyItems.filter(function(x){ return x.indexOf('其他:')===0; }).map(function(x){ return x.replace('其他:',''); })[0] || '';
    var lifeImpactItems = String(data.life_impact_issues || '').split('、').filter(Boolean);
    var lifeImpactOther = lifeImpactItems.filter(function(x){ return x.indexOf('其他:')===0; }).map(function(x){ return x.replace('其他:',''); })[0] || '';
    var lifeImpactWithoutOtherText = lifeImpactItems.filter(function (x) { return x.indexOf('其他:') !== 0; });
    if (lifeImpactOther && lifeImpactWithoutOtherText.indexOf('其他') === -1) {
      lifeImpactWithoutOtherText.push('其他');
    }
    document.getElementById('ha-diagnosed-disease-other').value = diagnosedOther;
    document.getElementById('ha-family-disease-other').value = familyOther;
    document.getElementById('ha-recent-symptom-other').value = symptomOther;
    document.getElementById('ha-life-impact-issue-other').value = lifeImpactOther;
    var checkGroups = { 'health-exercise-method': data.exercise_methods, 'health-need': data.health_needs, 'ha-diagnosed-disease': pastItems.filter(function(x){return x.indexOf('其他:')!==0;}), 'ha-family-disease': familyItems.filter(function(x){return x.indexOf('其他:')!==0;}), 'ha-special-condition': String(data.notes || '').split('、').filter(Boolean), 'ha-recent-symptom': symptomItems.filter(function(x){return x.indexOf('其他:')!==0;}), 'ha-life-impact-issue': lifeImpactWithoutOtherText };
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
