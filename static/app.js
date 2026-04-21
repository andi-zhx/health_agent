(function () {
  const API = '';
  function parseJsonResponse(r) {
    return r.text().then(function (text) {
      if (!text) return { success: false, message: '服务返回空响应', error_code: 'EMPTY_RESPONSE' };
      try {
        return JSON.parse(text);
      } catch (e) {
        var fallback = '服务返回异常，请刷新后重试';
        if (typeof text === 'string') {
          if (text.indexOf('<!doctype html') >= 0 || text.indexOf('<html') >= 0) {
            return { success: false, message: '服务端发生异常，请稍后重试', error_code: 'SERVER_ERROR' };
          }
          var shortText = text.trim();
          if (shortText) fallback = shortText.slice(0, 120);
        }
        return { success: false, message: fallback, error_code: 'INVALID_JSON' };
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
      return parseJsonResponse(response).then(function (payload) {
        var body = payload && typeof payload === 'object' ? payload : {};
        if (response.status === 401 && url !== '/api/auth/login') {
          showLoginScreen(body.message || '未登录或登录已失效，请重新登录');
        }
        if (!response.ok || body.success !== true) {
          return { error: body.message || ('请求失败(' + response.status + ')'), error_code: body.error_code || 'REQUEST_FAILED' };
        }
        return body.data == null ? {} : body.data;
      });
    }).catch(function () {
      return { error: '网络请求失败，请稍后重试' };
    });
  }

  function get(url) { return requestJson(url); }
  function post(url, body) { return requestJson(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }); }
  function postForm(url, formData) { return requestJson(url, { method: 'POST', body: formData }); }
  function put(url, body) { return requestJson(url, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }); }
  function del(url) { return requestJson(url, { method: 'DELETE' }); }

  function toList(data) {
    if (data && Array.isArray(data.items)) return data.items;
    return Array.isArray(data) ? data : [];
  }

  function getPagination(data) {
    return (data && data.pagination) || {};
  }

  function generateBookingGroupId() {
    // 前端一次提交多个时间段时，复用同一个分组ID，后端也会兜底生成。
    if (window.crypto && typeof window.crypto.randomUUID === 'function') {
      return window.crypto.randomUUID().replace(/-/g, '');
    }
    return String(Date.now()) + String(Math.random()).slice(2, 10);
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
    if (name === 'health') {
      if (typeof window !== 'undefined' && window.scrollTo) window.scrollTo({ top: 0, behavior: 'auto' });
      loadHealthPage();
    }
    if (name === 'portrait') loadPortraitPage();
    if (name === 'appointments') loadAppointmentsPage();
    if (name === 'home-appointments') loadHomeAppointmentsPage();
    if (name === 'improvement-tracking') loadImprovementTrackingPage();
    if (name === 'query-export') loadQueryExportPage();
    if (name === 'device-management') loadDeviceManagementPage();
    if (name === 'audit-logs') loadAuditLogsPage();
  }

  function loadQueryExportPage() {
    fillCustomerSelect('qe-customer');
    initNoShowDateRange();
    loadNoShowTop10Chart();
    get('/api/system/backup-path').then(function (res) {
      if (!res || res.error) return;
      document.getElementById('backup-path').value = res.backup_directory || '';
    });
    loadBackupList();
  }

  function formatDateInput(date) {
    if (!date) return '';
    var y = date.getFullYear();
    var m = String(date.getMonth() + 1).padStart(2, '0');
    var d = String(date.getDate()).padStart(2, '0');
    return y + '-' + m + '-' + d;
  }

  function initNoShowDateRange() {
    var startEl = document.getElementById('qe-no-show-start');
    var endEl = document.getElementById('qe-no-show-end');
    if (!startEl || !endEl) return;
    if (!startEl.value && !endEl.value) {
      var now = new Date();
      var begin = new Date(now.getTime());
      begin.setDate(begin.getDate() - 29);
      startEl.value = formatDateInput(begin);
      endEl.value = formatDateInput(now);
    }
  }

  function loadNoShowTop10Chart() {
    var chart = document.getElementById('qe-no-show-chart');
    if (!chart) return;
    var startDate = (document.getElementById('qe-no-show-start') || {}).value || '';
    var endDate = (document.getElementById('qe-no-show-end') || {}).value || '';
    if (startDate && endDate && startDate > endDate) {
      chart.innerHTML = '<p style="color:#c0392b">开始日期不能晚于结束日期</p>';
      return;
    }
    var params = [];
    if (startDate) params.push('start_date=' + encodeURIComponent(startDate));
    if (endDate) params.push('end_date=' + encodeURIComponent(endDate));
    var url = '/api/query-export/no-show-top10' + (params.length ? ('?' + params.join('&')) : '');
    get(url).then(function (res) {
      if (!res || res.error) {
        chart.innerHTML = '<p style="color:#c0392b">' + ((res && res.error) || '统计数据加载失败') + '</p>';
        return;
      }
      renderNoShowHorizontalBars('qe-no-show-chart', toList(res), '#f59e0b');
    });
  }

  function renderNoShowHorizontalBars(elId, list, color) {
    var box = document.getElementById(elId);
    if (!box) return;
    if (!list.length) {
      box.innerHTML = '<p style="color:#666">暂无爽约数据</p>';
      return;
    }
    var max = Math.max.apply(null, list.map(function (x) { return x.count || 0; }).concat([1]));
    box.innerHTML = list.map(function (x) {
      var width = Math.round(((x.count || 0) * 100) / max);
      return '<div class="bar-row"><div class="label" title="' + (x.name || '-') + '">' + (x.name || '-') + '</div><div class="bar-track"><div class="bar-fill" style="width:' + width + '%;background:' + color + '"></div></div><div class="value">' + (x.count || 0) + ' 次</div></div>';
    }).join('');
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
        {
          num: data.cumulative_service_count || 0,
          label: '累计服务人次',
          extra: '<div class="stat-extra"><div>男性人次：' + (data.male_service_count || 0) + '</div><div>女性人次：' + (data.female_service_count || 0) + '</div></div>'
        },
        { num: data.monthly_avg_service_count || 0, label: '月均服务人次' },
        { num: data.today_service_count || 0, label: '今日服务人次' }
      ].map(function (s) {
        return '<div class="stat-box"><div class="num">' + s.num + '</div><div class="label">' + s.label + '</div>' + (s.extra || '') + '</div>';
      }).join('');
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

  function buildPortraitRangeQuery() {
    var start = (document.getElementById('portrait-date-from') || {}).value || '';
    var end = (document.getElementById('portrait-date-to') || {}).value || '';
    var params = [];
    if (start) params.push('date_from=' + encodeURIComponent(start));
    if (end) params.push('date_to=' + encodeURIComponent(end));
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
  var improvementCustomerList = [];
  var improvementEditingId = null;
  var improvementViewOnly = false;
  var improvementMeta = null;
  var improvementPendingUploadFile = null;
  var portraitImprovementRankingRaw = [];
  var deviceManagementModalState = { mode: 'appointment', editId: '' };

  function equipmentStatusLabel(status) {
    return status === 'maintenance' ? '维修' : '可用';
  }

  function resetDeviceManagementModal() {
    deviceManagementModalState.mode = 'appointment';
    deviceManagementModalState.editId = '';
    document.getElementById('modal-dm-title').textContent = '新增服务项目';
    document.getElementById('modal-dm-edit-id').value = '';
    document.getElementById('modal-dm-type').value = 'appointment';
    document.getElementById('modal-dm-project-name').value = '';
    document.getElementById('modal-dm-equipment-name').value = '';
    document.getElementById('modal-dm-equipment-status').value = 'available';
    document.getElementById('modal-dm-equipment-location').value = '';
    document.getElementById('modal-dm-equipment-description').value = '';
    document.getElementById('modal-dm-staff-name').value = '';
    switchDeviceManagementModalType('appointment');
  }

  function switchDeviceManagementModalType(type) {
    var isAppointment = type !== 'home';
    document.getElementById('modal-dm-equipment-fields').classList.toggle('hide', !isAppointment);
    document.getElementById('modal-dm-home-fields').classList.toggle('hide', isAppointment);
  }

  function openDeviceManagementModal(mode, data) {
    resetDeviceManagementModal();
    var isEdit = !!data;
    var finalMode = mode === 'home' ? 'home' : 'appointment';
    deviceManagementModalState.mode = finalMode;
    deviceManagementModalState.editId = isEdit ? String(data.id || '') : '';
    document.getElementById('modal-dm-title').textContent = isEdit ? '编辑服务项目' : '新增服务项目';
    document.getElementById('modal-dm-edit-id').value = deviceManagementModalState.editId;
    document.getElementById('modal-dm-type').value = finalMode;
    document.getElementById('modal-dm-type').disabled = isEdit;
    switchDeviceManagementModalType(finalMode);
    if (isEdit) {
      document.getElementById('modal-dm-project-name').value = data.project_name || '';
      if (finalMode === 'appointment') {
        document.getElementById('modal-dm-equipment-name').value = data.equipment_name || '';
        document.getElementById('modal-dm-equipment-status').value = data.equipment_status || 'available';
        document.getElementById('modal-dm-equipment-location').value = data.equipment_location || '';
        document.getElementById('modal-dm-equipment-description').value = data.equipment_description || '';
      } else {
        document.getElementById('modal-dm-staff-name').value = data.staff_name || '';
      }
    }
    document.getElementById('modal-device-management').classList.remove('hide');
  }

  function closeDeviceManagementModal() {
    document.getElementById('modal-device-management').classList.add('hide');
    document.getElementById('modal-dm-type').disabled = false;
  }

  function loadDeviceManagementPage() {
    get('/api/device-management/appointment-items').then(function (res) {
      var rows = toList(res);
      var tbody = document.getElementById('dm-apt-list');
      if (!tbody) return;
      if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="5">暂无记录</td></tr>';
      } else {
        tbody.innerHTML = rows.map(function (row) {
          return '<tr>'
            + '<td>' + escapeHtml(row.project_name || '-') + '</td>'
            + '<td>' + escapeHtml(row.equipment_name || '-') + '</td>'
            + '<td>' + equipmentStatusLabel(row.equipment_status) + '</td>'
            + '<td>' + escapeHtml(row.created_at || '-') + '</td>'
            + '<td><button class="btn btn-secondary btn-small" data-dm-apt-edit="' + row.id + '">编辑</button></td>'
            + '</tr>';
        }).join('');
        tbody.querySelectorAll('[data-dm-apt-edit]').forEach(function (btn) {
          btn.addEventListener('click', function () {
            var id = this.getAttribute('data-dm-apt-edit');
            var picked = rows.find(function (x) { return String(x.id) === String(id); });
            if (!picked) return;
            openDeviceManagementModal('appointment', picked);
          });
        });
      }
    });

    get('/api/device-management/home-items').then(function (res) {
      var rows = toList(res);
      var tbody = document.getElementById('dm-home-list');
      if (!tbody) return;
      if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="4">暂无记录</td></tr>';
      } else {
        tbody.innerHTML = rows.map(function (row) {
          return '<tr>'
            + '<td>' + escapeHtml(row.project_name || '-') + '</td>'
            + '<td>' + escapeHtml(row.staff_name || '-') + '</td>'
            + '<td>' + escapeHtml(row.created_at || '-') + '</td>'
            + '<td><button class="btn btn-secondary btn-small" data-dm-home-edit="' + row.id + '">编辑</button></td>'
            + '</tr>';
        }).join('');
        tbody.querySelectorAll('[data-dm-home-edit]').forEach(function (btn) {
          btn.addEventListener('click', function () {
            var id = this.getAttribute('data-dm-home-edit');
            var picked = rows.find(function (x) { return String(x.id) === String(id); });
            if (!picked) return;
            openDeviceManagementModal('home', picked);
          });
        });
      }
    });
  }

  function setImprovementModalReadonly(isReadonly) {
    improvementViewOnly = !!isReadonly;
    var saveBtn = document.getElementById('btn-improvement-save');
    var uploadBtn = document.getElementById('btn-improvement-upload-file');
    var fieldSelectors = '#modal-improvement input, #modal-improvement select, #modal-improvement textarea';
    document.querySelectorAll(fieldSelectors).forEach(function (el) {
      if (!el || el.type === 'hidden' || el.id === 'improvement-service-id') return;
      if (el.tagName === 'SELECT') {
        el.disabled = improvementViewOnly;
      } else {
        el.readOnly = improvementViewOnly;
      }
    });
    if (saveBtn) saveBtn.style.display = improvementViewOnly ? 'none' : '';
    if (uploadBtn) uploadBtn.style.display = improvementViewOnly ? 'none' : '';
  }

  function setImprovementUploadStatus(text, isError, isUploading) {
    var el = document.getElementById('improvement-upload-status');
    if (!el) return;
    el.textContent = text || '';
    el.classList.remove('uploading');
    el.style.color = isError ? '#dc2626' : '';
    if (isUploading) el.classList.add('uploading');
  }
  var listState = {
    customers: { page: 1, page_size: 5 },
    customerHealth: { page: 1, page_size: 10 },
    customerAppointments: { page: 1, page_size: 10 },
    customerHomeAppointments: { page: 1, page_size: 10 },
    customerImprovement: { page: 1, page_size: 10 },
    health: { page: 1, page_size: 10 },
    appointments: { page: 1, page_size: 10 },
    homeAppointments: { page: 1, page_size: 10 },
    improvement: { page: 1, page_size: 10 },
    auditLogs: { page: 1, page_size: 10 }
  };
  var activeIntegratedTab = 'basic';
  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function selectedCustomerName() {
    var name = (document.getElementById('ha-name').value || '').trim();
    var phone = (document.getElementById('ha-phone').value || '').trim();
    return name + (phone ? (' ' + phone) : '');
  }

  function toDateTimeLocalValue(value) {
    var raw = String(value || '').trim();
    if (!raw) return '';
    var normalized = raw.replace('T', ' ');
    var m = normalized.match(/^(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})/);
    if (!m) return '';
    return m[1] + 'T' + m[2];
  }

  function normalizeServiceTimeForSave(value) {
    var raw = String(value || '').trim();
    if (!raw) return '';
    return raw.replace('T', ' ');
  }

  function renderImprovementCustomerOptions(keyword) {
    var optionBox = document.getElementById('improvement-customer-options');
    if (!optionBox) return;
    var q = String(keyword || '').trim();
    var matched = improvementCustomerList.filter(function (c) {
      var name = String(c.name || '');
      var phone = String(c.phone || '');
      return !q || name.indexOf(q) !== -1 || phone.indexOf(q) !== -1;
    });
    optionBox.innerHTML = matched.map(function (c) {
      var label = (c.name || '') + (c.phone ? ('（' + c.phone + '）') : '');
      return '<option value="' + escapeHtml(label) + '"></option>';
    }).join('');
  }

  function loadAuditLogsPage() {
    var state = listState.auditLogs || { page: 1, page_size: 10 };
    var params = [
      'page=' + encodeURIComponent(state.page || 1),
      'page_size=' + encodeURIComponent(state.page_size || 10)
    ];
    var startTime = (document.getElementById('audit-start-time') || {}).value || '';
    var endTime = (document.getElementById('audit-end-time') || {}).value || '';
    var operator = (document.getElementById('audit-operator') || {}).value || '';
    var module = (document.getElementById('audit-module') || {}).value || '';
    var action = (document.getElementById('audit-action') || {}).value || '';
    var keyword = (document.getElementById('audit-keyword') || {}).value || '';
    if (startTime) params.push('start_time=' + encodeURIComponent(startTime));
    if (endTime) params.push('end_time=' + encodeURIComponent(endTime));
    if (operator) params.push('operator=' + encodeURIComponent(operator));
    if (module) params.push('module=' + encodeURIComponent(module));
    if (action) params.push('action=' + encodeURIComponent(action));
    if (keyword) params.push('keyword=' + encodeURIComponent(keyword));
    get('/api/audit-logs?' + params.join('&')).then(function (res) {
      var rows = toList(res);
      var tbody = document.getElementById('audit-list');
      if (!tbody) return;
      if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="6">暂无日志记录</td></tr>';
      } else {
        tbody.innerHTML = rows.map(function (row) {
          return '<tr>'
            + '<td>' + (row.created_at || '-') + '</td>'
            + '<td>' + (row.username || '-') + '</td>'
            + '<td>' + (row.module || '-') + '</td>'
            + '<td>' + (row.action || '-') + '</td>'
            + '<td>' + (row.target_id || '-') + '</td>'
            + '<td>' + (row.details || '-') + '</td>'
            + '</tr>';
        }).join('');
      }
      renderAuditPagination(getPagination(res));
      showMsg('audit-msg', '');
    });
  }

  function renderAuditPagination(meta) {
    var box = document.getElementById('audit-pagination');
    if (!box) return;
    var page = meta.page || 1;
    var totalPages = meta.total_pages || 1;
    box.innerHTML = '<button ' + (page <= 1 ? 'disabled' : '') + ' data-page="prev">上一页</button>'
      + '<span>第 ' + page + ' / ' + totalPages + ' 页</span>'
      + '<button ' + (page >= totalPages ? 'disabled' : '') + ' data-page="next">下一页</button>';
    box.querySelectorAll('button').forEach(function (btn) {
      btn.addEventListener('click', function () {
        if (btn.dataset.page === 'prev' && listState.auditLogs.page > 1) listState.auditLogs.page -= 1;
        if (btn.dataset.page === 'next' && listState.auditLogs.page < totalPages) listState.auditLogs.page += 1;
        loadAuditLogsPage();
      });
    });
  }

  function renderListPagination(containerId, meta, stateKey, onChange) {
    var box = document.getElementById(containerId);
    if (!box) return;
    var page = meta.page || 1;
    var totalPages = meta.total_pages || 1;
    box.innerHTML = '<span>第 ' + page + ' / ' + totalPages + ' 页</span>'
      + '<button data-page-op="first"' + (page <= 1 ? ' disabled' : '') + '>第一页</button>'
      + '<button data-page-op="prev"' + (page <= 1 ? ' disabled' : '') + '>上一页</button>'
      + '<button data-page-op="next"' + (page >= totalPages ? ' disabled' : '') + '>下一页</button>'
      + '<button data-page-op="last"' + (page >= totalPages ? ' disabled' : '') + '>最后一页</button>';
    box.querySelectorAll('button').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var state = listState[stateKey];
        if (!state) return;
        var op = btn.getAttribute('data-page-op');
        if (op === 'first') state.page = 1;
        if (op === 'prev') state.page = Math.max(1, state.page - 1);
        if (op === 'next') state.page = Math.min(totalPages, state.page + 1);
        if (op === 'last') state.page = totalPages;
        onChange();
      });
    });
  }

  function applyImprovementCustomerByInput() {
    var input = document.getElementById('improvement-customer-search');
    var hidden = document.getElementById('improvement-customer');
    if (!input || !hidden) return;
    var raw = String(input.value || '').trim();
    if (!raw) {
      hidden.value = '';
      return;
    }
    var normalized = raw.replace(/[（）]/g, function (x) { return x === '（' ? '(' : ')'; });
    hidden.value = '';
    var exact = improvementCustomerList.find(function (c) {
      var label = (c.name || '') + (c.phone ? ('(' + c.phone + ')') : '');
      return label === normalized || (c.name || '') === raw || (c.phone || '') === raw;
    });
    if (!exact) return;
    hidden.value = exact.id;
    input.value = (exact.name || '') + (exact.phone ? ('（' + exact.phone + '）') : '');
  }

  function initImprovementCustomerPicker() {
    return get('/api/customers?page=1&page_size=500&sort_by=name_asc').then(function (list) {
      improvementCustomerList = toList(list);
      var searchInput = document.getElementById('improvement-customer-search');
      renderImprovementCustomerOptions(searchInput ? searchInput.value : '');
      applyImprovementCustomerByInput();
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
    var q = (document.getElementById('customer-search').value || '').trim();
    var qs = [
      'search=' + encodeURIComponent(q),
      'basic_page=' + listState.customers.page,
      'basic_page_size=' + listState.customers.page_size,
      'health_page=' + listState.customerHealth.page,
      'health_page_size=' + listState.customerHealth.page_size,
      'appointments_page=' + listState.customerAppointments.page,
      'appointments_page_size=' + listState.customerAppointments.page_size,
      'home_appointments_page=' + listState.customerHomeAppointments.page,
      'home_appointments_page_size=' + listState.customerHomeAppointments.page_size,
      'improvement_page=' + listState.customerImprovement.page,
      'improvement_page_size=' + listState.customerImprovement.page_size
    ];
    get('/api/customers/integrated-view?' + qs.join('&')).then(function (res) {
      if (!res || res.error) {
        showMsg('customer-msg', (res && res.error) || '加载失败', true);
        return;
      }
      var tbody = document.getElementById('customer-list');
      var basicData = res.basic || {};
      tbody.innerHTML = toList(basicData).map(function (c) {
        var createdAt = c.created_at ? String(c.created_at).replace('T', ' ').slice(0, 19) : '-';
        return '<tr><td>' + (c.name || '') + '</td><td>' + (c.age == null ? '-' : c.age) + '</td><td>' + (c.identity_type || '-') + '</td><td>' + (c.phone || '') + '</td><td>' + createdAt + '</td></tr>';
      }).join('');
      renderIntegratedSectionPagination('basic', basicData, 'customers');

      var healthTbody = document.getElementById('integrated-health-list');
      healthTbody.innerHTML = toList(res.health).map(function (h) {
        return '<tr><td>' + (h.customer_name || '-') + '</td><td>' + (h.assessment_date || '-') + '</td><td>' + (h.age == null ? '-' : h.age) + '</td><td>' + (h.recent_symptoms || '-') + '</td><td>' + (h.sleep_quality || '-') + '</td><td><button class="btn btn-small btn-secondary" data-int-health-detail="' + h.id + '">详细信息</button> <button class="btn btn-small btn-primary" data-int-health-jump="1">跳转详情页</button></td></tr><tr class="integrated-health-detail-row hide" data-int-health-detail-row="' + h.id + '"><td colspan="6"><div class="integrated-health-detail-content" data-int-health-detail-content="' + h.id + '">加载中...</div></td></tr>';
      }).join('');
      renderIntegratedSectionPagination('health', res.health || {}, 'customerHealth');

      var aptTbody = document.getElementById('integrated-appointments-list');
      aptTbody.innerHTML = toList(res.appointments).map(function (a) {
        return '<tr><td>' + (a.customer_name || '-') + '</td><td>' + (a.project_name || '-') + '</td><td>' + (a.appointment_date || '-') + '</td><td>' + ((a.start_time || '-') + '~' + (a.end_time || '-')) + '</td><td>' + renderCheckinStatusText(a.checkin_status) + '</td><td><button class="btn btn-small btn-secondary" data-int-apt-history="' + a.id + '">查看历史</button> <button class="btn btn-small btn-primary" data-int-apt-jump="1">跳转详情页</button></td></tr>';
      }).join('');
      renderIntegratedSectionPagination('appointments', res.appointments || {}, 'customerAppointments');

      var homeTbody = document.getElementById('integrated-home-list');
      homeTbody.innerHTML = toList(res.home_appointments).map(function (h) {
        return '<tr><td>' + (h.customer_name || '-') + '</td><td>' + (h.project_name || '-') + '</td><td>' + (h.appointment_date || '-') + '</td><td>' + ((h.start_time || '-') + '~' + (h.end_time || '-')) + '</td><td>' + renderCheckinStatusText(h.checkin_status) + '</td><td><button class="btn btn-small btn-secondary" data-int-home-history="' + h.id + '">查看历史</button> <button class="btn btn-small btn-primary" data-int-home-jump="1">跳转详情页</button></td></tr>';
      }).join('');
      renderIntegratedSectionPagination('home_appointments', res.home_appointments || {}, 'customerHomeAppointments');

      var improveTbody = document.getElementById('integrated-improvement-list');
      improveTbody.innerHTML = toList(res.improvement).map(function (r) {
        return '<tr><td>' + (r.customer_name || '-') + '</td><td>' + (r.service_project || '-') + '</td><td>' + (r.service_time || '-') + '</td><td>' + (r.improvement_status || '-') + '</td><td>' + (r.followup_date || r.followup_time || '-') + '</td><td><button class="btn btn-small btn-secondary" data-int-imp-view="' + r.id + '">详细信息</button> <button class="btn btn-small btn-primary" data-int-imp-jump="1">跳转详情页</button></td></tr><tr class="integrated-improvement-detail-row hide" data-int-imp-detail-row="' + r.id + '"><td colspan="6"><div class="integrated-health-detail-content" data-int-imp-detail-content="' + r.id + '">加载中...</div></td></tr>';
      }).join('');
      renderIntegratedSectionPagination('improvement', res.improvement || {}, 'customerImprovement');

      bindIntegratedSectionActions();
      renderIntegratedTabPanels();
      var p = getPagination(basicData);
      showMsg('customer-msg', '基础信息共 ' + (p.total || 0) + ' 条，当前第 ' + (p.page || 1) + ' / ' + (p.total_pages || 1) + ' 页');
    });
  }

  function renderIntegratedTabPanels() {
    document.querySelectorAll('[data-integrated-tab-btn]').forEach(function (btn) {
      btn.classList.toggle('active', btn.getAttribute('data-integrated-tab-btn') === activeIntegratedTab);
    });
    document.querySelectorAll('[data-integrated-tab-panel]').forEach(function (panel) {
      var key = panel.getAttribute('data-integrated-tab-panel');
      panel.classList.toggle('hide', key !== activeIntegratedTab);
    });
  }

  function renderCheckinStatusText(status) {
    var raw = String(status || '').toLowerCase();
    if (raw === 'checked_in') return '已签到';
    if (raw === 'no_show') return '爽约';
    if (raw === 'none') return '无';
    return '待签到';
  }

  function renderIntegratedSectionPagination(sectionKey, sectionData, stateKey) {
    var box = document.querySelector('[data-section-pagination="' + sectionKey + '"]');
    if (!box) return;
    var p = getPagination(sectionData);
    var page = p.page || 1;
    var totalPages = p.total_pages || 1;
    box.innerHTML = '<span>第 ' + page + ' / ' + totalPages + ' 页</span>'
      + '<button data-pg-first="' + stateKey + '"' + (page <= 1 ? ' disabled' : '') + '>第一页</button>'
      + '<button data-pg-prev="' + stateKey + '"' + (page <= 1 ? ' disabled' : '') + '>上一页</button>'
      + '<button data-pg-next="' + stateKey + '"' + (page >= totalPages ? ' disabled' : '') + '>下一页</button>'
      + '<button data-pg-last="' + stateKey + '"' + (page >= totalPages ? ' disabled' : '') + '>最后一页</button>';
    box.querySelectorAll('button').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var key = btn.getAttribute('data-pg-first') || btn.getAttribute('data-pg-prev') || btn.getAttribute('data-pg-next') || btn.getAttribute('data-pg-last');
        if (!listState[key]) return;
        if (btn.hasAttribute('data-pg-first')) listState[key].page = 1;
        if (btn.hasAttribute('data-pg-prev')) listState[key].page = Math.max(1, listState[key].page - 1);
        if (btn.hasAttribute('data-pg-next')) listState[key].page += 1;
        if (btn.hasAttribute('data-pg-last')) listState[key].page = totalPages;
        loadCustomers();
      });
    });
  }

  function bindIntegratedSectionActions() {
    document.querySelectorAll('[data-int-health-detail]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var detailId = btn.dataset.intHealthDetail;
        var detailRow = document.querySelector('[data-int-health-detail-row="' + detailId + '"]');
        var detailContent = document.querySelector('[data-int-health-detail-content="' + detailId + '"]');
        if (!detailRow || !detailContent) return;
        var isOpen = !detailRow.classList.contains('hide');
        document.querySelectorAll('.integrated-health-detail-row').forEach(function (row) {
          row.classList.add('hide');
        });
        if (isOpen) return;
        detailRow.classList.remove('hide');
        detailContent.innerHTML = '加载中...';
        get('/api/health-assessments/' + btn.dataset.intHealthDetail).then(function (data) {
          if (!data || data.error) {
            detailContent.innerHTML = '<span style="color:#ef4444">加载失败</span>';
            return;
          }
          var rows = buildHealthDetailRows(data);
          detailContent.innerHTML = rows.map(function (row) {
            return '<div><strong>' + escapeHtml(row[0]) + '：</strong>' + escapeHtml(row[1] || '-') + '</div>';
          }).join('');
        });
      });
    });
    document.querySelectorAll('[data-int-apt-history]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        viewBusinessHistory('appointments', btn.dataset.intAptHistory, '预约服务 - 业务历史日志');
      });
    });
    document.querySelectorAll('[data-int-home-history]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        viewBusinessHistory('home_appointments', btn.dataset.intHomeHistory, '上门预约 - 业务历史日志');
      });
    });
    document.querySelectorAll('[data-int-health-jump]').forEach(function (btn) {
      btn.addEventListener('click', function () { showPage('health'); });
    });
    document.querySelectorAll('[data-int-apt-jump]').forEach(function (btn) {
      btn.addEventListener('click', function () { showPage('appointments'); });
    });
    document.querySelectorAll('[data-int-home-jump]').forEach(function (btn) {
      btn.addEventListener('click', function () { showPage('home-appointments'); });
    });
    document.querySelectorAll('[data-int-imp-view]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var detailId = btn.dataset.intImpView;
        var detailRow = document.querySelector('[data-int-imp-detail-row="' + detailId + '"]');
        var detailContent = document.querySelector('[data-int-imp-detail-content="' + detailId + '"]');
        if (!detailRow || !detailContent) return;
        var isOpen = !detailRow.classList.contains('hide');
        document.querySelectorAll('.integrated-improvement-detail-row').forEach(function (row) {
          row.classList.add('hide');
        });
        if (isOpen) return;
        detailRow.classList.remove('hide');
        detailContent.innerHTML = '加载中...';
        get('/api/improvement-records/' + btn.dataset.intImpView).then(function (data) {
          if (!data || data.error) {
            detailContent.innerHTML = '<span style="color:#ef4444">加载失败</span>';
            return;
          }
          var rows = buildImprovementDetailRows(data);
          detailContent.innerHTML = rows.map(function (row) {
            return '<div><strong>' + escapeHtml(row[0]) + '：</strong>' + escapeHtml(row[1] || '-') + '</div>';
          }).join('');
        });
      });
    });
    document.querySelectorAll('[data-int-imp-jump]').forEach(function (btn) {
      btn.addEventListener('click', function () { showPage('improvement-tracking'); });
    });
  }

  function buildImprovementDetailRows(data) {
    return [
      ['客户', data.customer_name],
      ['服务项目', data.service_project],
      ['服务时间', data.service_time],
      ['服务前状态', data.pre_service_status],
      ['服务内容', data.service_content],
      ['服务后评价', data.post_service_evaluation],
      ['改善情况', data.improvement_status],
      ['随访日期', data.followup_date],
      ['随访时间', data.followup_time],
      ['随访方式', data.followup_method]
    ];
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

  function calculateAgeByBirthYear(dateStr) {
    if (!dateStr) return '';
    var date = new Date(dateStr + 'T00:00:00');
    if (isNaN(date.getTime())) return '';
    var currentYear = new Date().getFullYear();
    return String(currentYear - date.getFullYear());
  }

  function syncAgeFieldByBirthDate(birthDateId, ageId) {
    var birthDateValue = (document.getElementById(birthDateId).value || '').trim();
    document.getElementById(ageId).value = calculateAgeByBirthYear(birthDateValue);
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
        syncAgeFieldByBirthDate('mc-birth_date', 'mc-age');
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

  function buildHealthDetailRows(data) {
    return [
      ['客户', data.customer_name], ['手机号', data.phone], ['身份证号', data.id_card], ['性别', data.gender], ['出生日期', data.birth_date],
      ['身份', data.identity_type], ['军衔', data.military_rank], ['建档人', data.record_creator], ['评估日期', data.assessment_date], ['年龄', data.age],
      ['身高(cm)', data.height_cm], ['体重(kg)', data.weight_kg], ['地址', data.address], ['既往病史', data.past_medical_history],
      ['家族慢性病史', data.family_history], ['过敏史', data.allergy_history], ['过敏详情', data.allergy_details], ['吸烟情况', data.smoking_status],
      ['烟龄', data.smoking_years], ['日均吸烟量', data.cigarettes_per_day], ['饮酒情况', data.drinking_status], ['饮酒年限', data.drinking_years],
      ['睡眠状况', data.sleep_quality], ['睡眠时长', data.sleep_hours], ['近半年症状', data.recent_symptoms], ['详细情况', data.recent_symptom_detail],
      ['最影响生活的问题', data.life_impact_issues], ['近半年血压', data.blood_pressure_test],
      ['近半年血脂', data.blood_lipid_test], ['近半年血糖', data.blood_sugar_test],
      ['慢性疼痛', data.chronic_pain], ['疼痛详情', data.pain_details], ['运动方式', (data.exercise_methods || []).join('、')], ['健康需求', (data.health_needs || []).join('、')], ['特殊情况', data.notes]
    ];
  }

  function renderHealthDetail(data, options) {
    var box = document.getElementById('health-detail');
    if (!box) return;
    if (!data || !data.id) {
      box.style.display = 'none';
      box.innerHTML = '';
      selectedHealthDetailId = '';
      return;
    }
    selectedHealthDetailId = String(data.id);
    var rows = buildHealthDetailRows(data);
    box.innerHTML = '<h3 style="margin-top:0">档案详细信息</h3>' + rows.map(function (row) {
      return '<div><strong>' + escapeHtml(row[0]) + '：</strong>' + escapeHtml(row[1] || '-') + '</div>';
    }).join('');
    box.style.display = 'block';
    if (options && options.scrollToDetail) {
      box.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }

  function loadHealthPage() {
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
        var diagnosed = h.past_medical_history && String(h.past_medical_history).trim() ? '是' : '否';
        return '<tr><td>' + (h.customer_name || '') + '</td><td>' + (h.age == null ? '-' : h.age) + '</td><td>' + diagnosed + '</td><td>' + (h.recent_symptoms || '-') + '</td><td>' + (h.sleep_quality || '-') + '</td><td><button class="btn btn-small btn-secondary" data-health-detail="' + h.id + '">详细信息</button> <button class="btn btn-small btn-primary" data-health-edit="' + h.id + '">编辑</button> <button class="btn btn-small btn-primary" data-health-improvement-customer="' + h.customer_id + '">查看改善记录</button></td></tr>';
      }).join('');
      tbody.querySelectorAll('[data-health-detail]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          get('/api/health-assessments/' + btn.dataset.healthDetail).then(function (data) {
            renderHealthDetail(data || {}, { scrollToDetail: true });
          });
        });
      });
      tbody.querySelectorAll('[data-health-edit]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          get('/api/health-assessments/' + btn.dataset.healthEdit).then(function (data) {
            if (data && data.customer_id) {
              get('/api/customers/' + data.customer_id).then(function (customer) {
                var merged = Object.assign({}, data || {}, customer || {});
                editingHealthSnapshot = merged && merged.id ? JSON.parse(JSON.stringify(merged)) : null;
                setHealthEditMode(!!(merged && merged.id));
                fillHealthForm(merged);
              });
              return;
            }
            editingHealthSnapshot = data && data.id ? JSON.parse(JSON.stringify(data)) : null;
            setHealthEditMode(!!(data && data.id));
            fillHealthForm(data || {});
          });
        });
      });
      tbody.querySelectorAll('[data-health-improvement-customer]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          showPage('improvement-tracking');
          loadImprovementTrackingPage(btn.dataset.healthImprovementCustomer);
        });
      });
      var p = getPagination(list);
      showMsg('health-msg', '共 ' + (p.total || 0) + ' 条，当前第 ' + (p.page || 1) + ' / ' + (p.total_pages || 1) + ' 页');
      renderListPagination('health-pagination', p, 'health', loadHealthPage);
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
    setCompanionRadio('apt-has-companion', '无');
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
    var equipmentList = (selectedAppointmentSlot.available_equipment || []).concat(selectedAppointmentSlot.maintenance_equipment || []);
    if (!equipmentList.length) {
      box.innerHTML = '<div class="appointment-tip">该时间段暂无可选设备</div>';
      return;
    }
    box.innerHTML = equipmentList.map(function (item) {
      var active = String(selectedAppointmentEquipmentId) === String(item.id) && item.status === 'available';
      var disabled = item.status === 'maintenance';
      var model = String(item.model || '').trim() || String(item.name || '').slice(-2);
      var statusText = disabled ? '正在维修，不可预约' : '可预约';
      return '<label class="equipment-item ' + (active ? 'active' : '') + '" style="' + (disabled ? 'opacity:.55;cursor:not-allowed' : '') + '">' +
        '<input type="radio" name="apt-equipment-radio" value="' + item.id + '" ' + (active ? 'checked' : '') + ' ' + (disabled ? 'disabled' : '') + '>' +
        '<div><div class="name">' + escapeHtml(item.name || '-') + '</div><div class="detail">设备' + escapeHtml(model) + '｜' + statusText + '</div></div>' +
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
      var meta = isAvailable ? ('可预约｜剩余设备 ' + (slot.available_equipment_count || 0) + ' 台') : (slot.status === 'maintenance' ? '正在维修，不可预约' : '已约满');
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
            maintenance_equipment: picked.maintenance_equipment || [],
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
    setCompanionRadio('home-has-companion', '无');
    homeSlotPanel = [];
    homeStaffPanel = null;
    selectedHomeSlot = null;
    selectedHomeSlots = [];
    renderHomeSlotPanel();
    renderHomeStaffPanel();
  }

  function getStatusMeta(status) {
    var raw = String(status || '').toLowerCase();
    if (raw === 'completed') {
      return { text: '服务完成', cls: 'status-pill-completed', editable: false };
    }
    if (raw === 'cancelled') {
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
    if (checkinStatus === 'none') return { text: '无', cls: '' };
    if (checkinStatus === 'checked_in') return { text: '已签到', cls: 'checkin-btn-checked' };
    if (checkinStatus === 'no_show') return { text: '爽约', cls: 'checkin-btn-noshow' };
    return { text: '待签到', cls: 'checkin-btn-pending' };
  }

  function canOperateCheckin(record) {
    var bookingStatus = String(record.status || '').toLowerCase();
    var checkinStatus = String(record.checkin_status || 'pending').toLowerCase();
    return bookingStatus !== 'cancelled' && checkinStatus === 'pending' && String(record.appointment_date || '') === today;
  }

  function canCompleteService(record) {
    var bookingStatus = String(record.status || '').toLowerCase();
    var checkinStatus = String(record.checkin_status || 'pending').toLowerCase();
    return bookingStatus === 'scheduled' && checkinStatus === 'checked_in';
  }

  function renderCheckinCell(record, moduleName) {
    var bookingStatus = String(record.status || '').toLowerCase();
    var checkinStatus = String(record.checkin_status || 'pending').toLowerCase();
    var meta = getCheckinMeta(checkinStatus, bookingStatus);
    if (bookingStatus === 'cancelled' || checkinStatus === 'none') return '<span>-</span>';
    return '<button class="checkin-btn ' + meta.cls + '" type="button" disabled>' + meta.text + '</button>';
  }

  function renderRowActionMenu(record, type) {
    var id = record.id;
    var meta = getStatusMeta(record.status);
    var items = [
      '<button class="row-action-item" type="button" data-' + type + '-history="' + id + '">查看历史</button>',
      '<button class="row-action-item" type="button" data-' + type + '-improvement="' + id + '">填写改善情况</button>'
    ];
    if (meta.editable) {
      items.splice(1, 0, '<button class="row-action-item" type="button" data-' + type + '-edit="' + id + '">编辑</button>');
      items.push('<button class="row-action-item danger" type="button" data-' + type + '-cancel="' + id + '">取消预约</button>');
    }
    if (canOperateCheckin(record)) {
      items.push('<button class="row-action-item" type="button" data-checkin-action="' + (type === 'apt' ? 'appointments' : 'home_appointments') + '" data-checkin-id="' + id + '" data-checkin-target="checked_in">标记已签到</button>');
      items.push('<button class="row-action-item" type="button" data-checkin-action="' + (type === 'apt' ? 'appointments' : 'home_appointments') + '" data-checkin-id="' + id + '" data-checkin-target="no_show">标记爽约</button>');
    }
    if (canCompleteService(record)) {
      items.push('<button class="row-action-item" type="button" data-complete-action="' + (type === 'apt' ? 'appointments' : 'home_appointments') + '" data-complete-id="' + id + '">完成服务</button>');
    }
    return '<details class="row-action-menu"><summary class="row-action-trigger">操作</summary><div class="row-action-list">' + items.join('') + '</div></details>';
  }

  function closeRowActionMenusExcept(target) {
    document.querySelectorAll('.row-action-menu[open]').forEach(function (menu) {
      if (target && menu.contains(target)) return;
      menu.removeAttribute('open');
    });
  }

  function loadAppointmentsPage() {
    setAppointmentEditMode(null);
    appointmentSlotPanel = null;
    resetAppointmentSlotSelection();
    renderAppointmentSlotPanel();
    fillCustomerSelect('apt-customer');
    var aptCustomerInput = document.getElementById('apt-customer-search');
    if (aptCustomerInput) aptCustomerInput.value = '';
    fillProjectSelect('apt-project', true, 'store');
    var sortBy = (document.getElementById('apt-sort') || {}).value || 'time_desc';
    var historySearch = (document.getElementById('apt-history-search') || {}).value || '';
    var qs = [
      'sort_by=' + encodeURIComponent(sortBy),
      'page=' + listState.appointments.page,
      'page_size=' + listState.appointments.page_size
    ];
    var statusFilter = (document.getElementById('apt-status-filter') || {}).value || '';
    var checkinFilter = (document.getElementById('apt-checkin-filter') || {}).value || '';
    if (statusFilter) qs.push('status=' + encodeURIComponent(statusFilter));
    if (checkinFilter) qs.push('checkin_status=' + encodeURIComponent(checkinFilter));
    if (historySearch.trim()) qs.push('search=' + encodeURIComponent(historySearch.trim()));
    get('/api/appointments?' + qs.join('&')).then(function (list) {
      var tbody = document.getElementById('apt-list');
      tbody.innerHTML = toList(list).map(function (a) {
        var action = renderRowActionMenu(a, 'apt');
        return '<tr><td>' + (a.customer_name || '') + '</td><td>' + (a.project_name || '-') + '</td><td>' + (a.equipment_name || '-') + '</td><td>' + (a.appointment_date || '') + '</td><td>' + (a.start_time || '') + '~' + (a.end_time || '') + '</td><td>' + renderStatusPill(a.status) + '</td><td>' + renderCheckinCell(a, 'appointments') + '</td><td>' + action + '</td><td>' + renderOperationTime(a) + '</td></tr>';
      }).join('');
      var p = getPagination(list);
      showMsg('apt-msg', '共 ' + (p.total || 0) + ' 条，当前第 ' + (p.page || 1) + ' / ' + (p.total_pages || 1) + ' 页');
      renderListPagination('apt-pagination', p, 'appointments', loadAppointmentsPage);
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
          setCompanionRadio('apt-has-companion', item.has_companion || '无');
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
      tbody.querySelectorAll('[data-apt-improvement]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          get('/api/improvement-records/from-appointment?service_id=' + encodeURIComponent(btn.dataset.aptImprovement) + '&service_type=appointments').then(function (draft) {
            if (!draft || draft.error) { showMsg('apt-msg', (draft && draft.error) || '初始化改善记录失败', true); return; }
            showPage('improvement-tracking');
            openImprovementModal(draft, '填写改善情况');
          });
        });
      });
      tbody.querySelectorAll('[data-complete-action="appointments"]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          post('/api/appointments/' + btn.dataset.completeId + '/complete', {}).then(function (res) {
            if (res.error) { showMsg('apt-msg', res.error, true); return; }
            showMsg('apt-msg', '服务状态已更新为已完成');
            loadAppointmentsPage();
          });
        });
      });
      tbody.querySelectorAll('[data-apt-cancel]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          openConfirmModal('确认修改预约状态', [['状态', '取消预约']], function () {
            post('/api/appointments/' + btn.dataset.aptCancel + '/cancel', {}).then(function (res) {
              if (res.error) { showMsg('apt-msg', res.error, true); return; }
              showMsg('apt-msg', '已更新为取消预约');
              loadAppointmentsPage();
            });
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
    var historySearch = (document.getElementById('home-history-search') || {}).value || '';
    var qs = [
      'sort_by=' + encodeURIComponent(sortBy),
      'page=' + listState.homeAppointments.page,
      'page_size=' + listState.homeAppointments.page_size
    ];
    var statusFilter = (document.getElementById('home-status-filter') || {}).value || '';
    var checkinFilter = (document.getElementById('home-checkin-filter') || {}).value || '';
    if (statusFilter) qs.push('status=' + encodeURIComponent(statusFilter));
    if (checkinFilter) qs.push('checkin_status=' + encodeURIComponent(checkinFilter));
    if (historySearch.trim()) qs.push('search=' + encodeURIComponent(historySearch.trim()));
    get('/api/home-appointments?' + qs.join('&')).then(function (list) {
      var rows = toList(list);
      var tbody = document.getElementById('home-list');
      tbody.innerHTML = rows.map(function (a) {
        var action = renderRowActionMenu(a, 'home');
        return '<tr><td>' + (a.customer_name || '') + '</td><td>' + (a.project_name || '-') + '</td><td>' + (a.appointment_date || '') + '</td><td>' + (a.start_time || '') + '~' + (a.end_time || '') + '</td><td>' + (a.location || '-') + '</td><td>' + (a.staff_name || '-') + '</td><td>' + renderStatusPill(a.status) + '</td><td>' + renderCheckinCell(a, 'home_appointments') + '</td><td>' + action + '</td><td>' + renderOperationTime(a) + '</td></tr>';
      }).join('');
      var p = getPagination(list);
      showMsg('home-msg', '共 ' + (p.total || 0) + ' 条，当前第 ' + (p.page || 1) + ' / ' + (p.total_pages || 1) + ' 页');
      renderListPagination('home-pagination', p, 'homeAppointments', loadHomeAppointmentsPage);
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
          setCompanionRadio('home-has-companion', item.has_companion || '无');
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
      tbody.querySelectorAll('[data-home-improvement]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          get('/api/improvement-records/from-appointment?service_id=' + encodeURIComponent(btn.dataset.homeImprovement) + '&service_type=home_appointments').then(function (draft) {
            if (!draft || draft.error) { showMsg('home-msg', (draft && draft.error) || '初始化改善记录失败', true); return; }
            showPage('improvement-tracking');
            openImprovementModal(draft, '填写改善情况');
          });
        });
      });
      tbody.querySelectorAll('[data-complete-action="home_appointments"]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          post('/api/home-appointments/' + btn.dataset.completeId + '/complete', {}).then(function (res) {
            if (res.error) { showMsg('home-msg', res.error, true); return; }
            showMsg('home-msg', '服务状态已更新为已完成');
            loadHomeAppointmentsPage();
          });
        });
      });
      tbody.querySelectorAll('[data-home-cancel]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          openConfirmModal('确认修改预约状态', [['状态', '取消预约']], function () {
            post('/api/home-appointments/' + btn.dataset.homeCancel + '/cancel', {}).then(function (res) {
              if (res.error) { showMsg('home-msg', res.error, true); return; }
              showMsg('home-msg', '已更新为取消预约');
              loadHomeAppointmentsPage();
            });
          });
        });
      });
    });
  }

  function ensureImprovementMeta() {
    if (improvementMeta) return Promise.resolve(improvementMeta);
    return get('/api/improvement-records/meta').then(function (res) {
      if (!res || res.error) return null;
      improvementMeta = res;
      var projectOptions = '<option value="">全部服务项目</option>' + toList(res.service_projects).map(function (x) { return '<option value="' + x + '">' + x + '</option>'; }).join('');
      var statusOptions = '<option value="">全部改善情况</option>' + toList(res.improvement_status_options).map(function (x) { return '<option value="' + x + '">' + x + '</option>'; }).join('');
      var projectFilter = document.getElementById('improvement-filter-service-project');
      var statusFilter = document.getElementById('improvement-filter-status');
      if (projectFilter) projectFilter.innerHTML = projectOptions;
      if (statusFilter) statusFilter.innerHTML = statusOptions;
      return res;
    });
  }

  function fillImprovementFormOptions() {
    var meta = improvementMeta || {};
    var projectSel = document.getElementById('improvement-service-project');
    var statusSel = document.getElementById('improvement-status');
    var followupTimeSel = document.getElementById('improvement-followup-time');
    var followupMethodSel = document.getElementById('improvement-followup-method');
    if (projectSel) projectSel.innerHTML = '<option value="">请选择服务项目</option>' + toList(meta.service_projects).map(function (x) { return '<option value="' + x + '">' + x + '</option>'; }).join('');
    if (statusSel) statusSel.innerHTML = '<option value="">请选择改善情况</option>' + toList(meta.improvement_status_options).map(function (x) { return '<option value="' + x + '">' + x + '</option>'; }).join('');
    if (followupTimeSel) followupTimeSel.innerHTML = '<option value="">请选择随访时间</option>' + toList(meta.followup_time_options).map(function (x) { return '<option value="' + x + '">' + x + '</option>'; }).join('');
    if (followupMethodSel) followupMethodSel.innerHTML = '<option value="">请选择随访方式</option>' + toList(meta.followup_method_options).map(function (x) { return '<option value="' + x + '">' + x + '</option>'; }).join('');
  }

  function openImprovementModal(record, modeText, options) {
    ensureImprovementMeta().then(function () {
      initImprovementCustomerPicker().then(function () {
        fillImprovementFormOptions();
        var opts = options || {};
        var isViewOnly = !!opts.viewOnly;
        var data = record || {};
        improvementEditingId = data.id || null;
        document.getElementById('improvement-modal-title').textContent = modeText || (improvementEditingId ? '编辑改善记录' : '新增改善记录');
        document.getElementById('improvement-id').value = data.id || '';
        document.getElementById('improvement-service-id').value = data.service_id || '';
        document.getElementById('improvement-service-type').value = data.service_type || 'appointments';
        var customerInput = document.getElementById('improvement-customer-search');
        var customerHidden = document.getElementById('improvement-customer');
        if (customerHidden) customerHidden.value = data.customer_id || '';
        if (customerInput) {
          var selected = improvementCustomerList.find(function (c) { return String(c.id) === String(data.customer_id || ''); });
          customerInput.value = selected
            ? ((selected.name || '') + (selected.phone ? ('（' + selected.phone + '）') : ''))
            : (data.customer_name || '');
        }
        document.getElementById('improvement-service-time').value = toDateTimeLocalValue(data.service_time || '');
        document.getElementById('improvement-service-project').value = data.service_project || '';
        document.getElementById('improvement-pre-service-status').value = data.pre_service_status || '';
        document.getElementById('improvement-service-content').value = data.service_content || '';
        document.getElementById('improvement-post-service-evaluation').value = data.post_service_evaluation || '';
        document.getElementById('improvement-status').value = data.improvement_status || '';
        document.getElementById('improvement-followup-time').value = data.followup_time || '';
        document.getElementById('improvement-followup-date').value = data.followup_date || '';
        document.getElementById('improvement-followup-method').value = data.followup_method || '';
        setImprovementUploadStatus('', false, false);
        improvementPendingUploadFile = null;
        setImprovementModalReadonly(isViewOnly);
        document.getElementById('modal-improvement').classList.remove('hide');
      });
    });
  }

  function closeImprovementUploadModal() {
    var uploadInput = document.getElementById('improvement-upload-input');
    if (uploadInput) uploadInput.value = '';
    document.getElementById('modal-improvement-upload').classList.add('hide');
  }

  function uploadImprovementFile(file) {
    if (!file) return;
    improvementPendingUploadFile = file;
    setImprovementUploadStatus('已选择文件：' + (file.name || '未命名文件') + '，保存理疗记录后将自动上传', false, false);
    closeImprovementUploadModal();
  }

  function uploadImprovementFileForRecord(rid, file) {
    if (!rid || !file) return Promise.resolve({ success: true });
    var formData = new FormData();
    formData.append('file', file);
    setImprovementUploadStatus('正在上传中...', false, true);
    return postForm('/api/improvement-records/' + encodeURIComponent(rid) + '/files', formData).then(function (res) {
      if (!res || res.error) {
        setImprovementUploadStatus((res && res.error) || '文件上传失败', true, false);
        return { success: false, error: (res && res.error) || '文件上传失败' };
      }
      setImprovementUploadStatus('上传成功：' + (res.file_name || file.name || ''), false, false);
      improvementPendingUploadFile = null;
      closeImprovementUploadModal();
      return { success: true };
    });
  }

  function loadImprovementTrackingPage(customerId) {
    ensureImprovementMeta().then(function () {
      var qs = [];
      var customerName = (document.getElementById('improvement-filter-customer-name').value || '').trim();
      var serviceProject = (document.getElementById('improvement-filter-service-project').value || '').trim();
      var status = (document.getElementById('improvement-filter-status').value || '').trim();
      var serviceStart = (document.getElementById('improvement-filter-start').value || '').trim();
      var serviceEnd = (document.getElementById('improvement-filter-end').value || '').trim();
      if (customerId) qs.push('customer_id=' + encodeURIComponent(customerId));
      if (customerName) qs.push('customer_keyword=' + encodeURIComponent(customerName));
      if (serviceProject) qs.push('service_project=' + encodeURIComponent(serviceProject));
      if (status) qs.push('improvement_status=' + encodeURIComponent(status));
      if (serviceStart) qs.push('service_start=' + encodeURIComponent(serviceStart));
      if (serviceEnd) qs.push('service_end=' + encodeURIComponent(serviceEnd));
      qs.push('page=' + encodeURIComponent(listState.improvement.page || 1));
      qs.push('page_size=' + encodeURIComponent(listState.improvement.page_size || 10));
      get('/api/improvement-records/all' + (qs.length ? ('?' + qs.join('&')) : '')).then(function (res) {
        if (!res || res.error) {
          showMsg('improvement-msg', (res && res.error) || '加载失败', true);
          return;
        }
        var rows = toList(res);
        var tbody = document.getElementById('improvement-list');
        tbody.innerHTML = rows.map(function (row) {
          return '<tr><td>' + (row.customer_name || '-') + '</td><td>' + (row.service_project || '-') + '</td><td>' + (row.service_time || '-') + '</td><td>' + (row.improvement_status || '-') + '</td><td>' + (row.followup_date || row.followup_time || '-') + '</td><td>' + (row.followup_method || '-') + '</td><td><button class="btn btn-small btn-secondary" data-improvement-view="' + row.id + '">查看</button> <button class="btn btn-small btn-primary" data-improvement-edit="' + row.id + '">编辑</button> <button class="btn btn-small btn-danger" data-improvement-del="' + row.id + '">删除</button></td></tr>';
        }).join('');
        var p = getPagination(res);
        showMsg('improvement-msg', '共 ' + (p.total || 0) + ' 条改善记录，当前第 ' + (p.page || 1) + ' / ' + (p.total_pages || 1) + ' 页');
        renderListPagination('improvement-pagination', p, 'improvement', function () { loadImprovementTrackingPage(customerId); });
        tbody.querySelectorAll('[data-improvement-view]').forEach(function (btn) {
          btn.addEventListener('click', function () {
            get('/api/improvement-records/' + btn.dataset.improvementView).then(function (row) {
              if (!row || row.error) { showMsg('improvement-msg', (row && row.error) || '加载失败', true); return; }
              openImprovementModal(row, '查看改善记录', { viewOnly: true });
            });
          });
        });
        tbody.querySelectorAll('[data-improvement-edit]').forEach(function (btn) {
          btn.addEventListener('click', function () {
            get('/api/improvement-records/' + btn.dataset.improvementEdit).then(function (row) {
              if (!row || row.error) { showMsg('improvement-msg', (row && row.error) || '加载失败', true); return; }
              openImprovementModal(row, '编辑改善记录');
            });
          });
        });
        tbody.querySelectorAll('[data-improvement-del]').forEach(function (btn) {
          btn.addEventListener('click', function () {
            if (!window.confirm('确定删除该改善记录吗？')) return;
            del('/api/improvement-records/' + btn.dataset.improvementDel).then(function (ret) {
              if (ret && ret.error) { showMsg('improvement-msg', ret.error, true); return; }
              showMsg('improvement-msg', '删除成功');
              loadImprovementTrackingPage();
            });
          });
        });
      });
    });
  }

  function loadImprovementPendingRecords() {
    get('/api/improvement-records/pending-fill').then(function (res) {
      if (!res || res.error) {
        showMsg('improvement-msg', (res && res.error) || '待填写记录加载失败', true);
        return;
      }
      var rows = toList(res);
      var tbody = document.getElementById('improvement-list');
      tbody.innerHTML = rows.map(function (row) {
        return '<tr><td>' + (row.customer_name || '-') + '</td><td>' + (row.service_project || '-') + '</td><td>' + (row.service_time || '-') + '</td><td>待填写</td><td>-</td><td>-</td><td><button class="btn btn-small btn-primary" data-improvement-pending-fill="' + row.service_type + ':' + row.service_id + '">填写改善情况</button></td></tr>';
      }).join('');
      showMsg('improvement-msg', '待填写记录共 ' + rows.length + ' 条');
      var improvementPagination = document.getElementById('improvement-pagination');
      if (improvementPagination) improvementPagination.innerHTML = '';
      tbody.querySelectorAll('[data-improvement-pending-fill]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          var val = btn.dataset.improvementPendingFill || '';
          var parts = val.split(':');
          if (parts.length !== 2) return;
          var serviceType = (parts[0] || '').trim();
          var serviceId = (parts[1] || '').trim();
          if (!serviceType || !serviceId) return;
          get('/api/improvement-records/from-appointment?service_id=' + encodeURIComponent(serviceId) + '&service_type=' + encodeURIComponent(serviceType)).then(function (draft) {
            if (!draft || draft.error) { showMsg('improvement-msg', (draft && draft.error) || '初始化改善记录失败', true); return; }
            openImprovementModal(draft, '填写改善情况');
          });
        });
      });
    });
  }

  function loadPortraitPage() {
    var start = (document.getElementById('portrait-date-from') || {}).value || '';
    var end = (document.getElementById('portrait-date-to') || {}).value || '';
    if (start && end && start > end) {
      showMsg('portrait-msg', '开始日期不能晚于结束日期', true);
      return;
    }
    get('/api/dashboard/health-portrait' + buildPortraitRangeQuery()).then(function (res) {
      if (res.error) {
        showMsg('portrait-msg', res.error, true);
        return;
      }
      var d1 = res.dimension1 || {};
      var d2 = res.dimension2 || {};
      var d3 = res.dimension3 || {};
      var abnormalIndicators = toList(res.abnormal_indicators);
      var scopeText = (res.filter_applied ? '按所选时间范围' : '按全量最新档案');
      showMsg('portrait-msg', '已' + scopeText + '生成画像，当前统计样本量：' + (res.total_customers || 0) + ' 人');
      var noteBox = document.getElementById('portrait-caliber-note');
      if (noteBox) noteBox.textContent = res.sampling_note || '';
      renderKpiCards('portrait-abnormal-kpi-cards', abnormalIndicators.map(function (item) {
        return {
          name: item.name || '-',
          value: (item.count || 0) + '人 / ' + (item.ratio || 0) + '%'
        };
      }));
      renderKpiCards('portrait-kpi-cards', [
        { name: '总人数', value: (d1.cards || {}).total_people || 0 },
        { name: 'BMI异常率', value: ((d1.cards || {}).bmi_abnormal_rate || 0) + '%' },
        { name: '66岁以上占比', value: ((d1.cards || {}).senior_ratio || 0) + '%' }
      ]);
      renderCircleChart('portrait-gender-pie', toList(d1.gender_distribution), false);
      renderLegend('portrait-gender-legend', toList(d1.gender_distribution));
      renderAgeGenderCompare('portrait-age-gender-bars', toList(d1.age_gender_distribution));
      renderCircleChart('portrait-bmi-pie', toList(d1.bmi_distribution), false);
      renderLegend('portrait-bmi-legend', toList(d1.bmi_distribution));
      renderHorizontalBars('portrait-disease-top10', toList(d2.past_disease_distribution), '#f59e0b', { maxItems: 10 });
      renderHorizontalBars('portrait-family-top10', toList(d2.family_history_distribution), '#fb7185', { maxItems: 10 });
      renderHorizontalBars('portrait-recent-symptom-bars', toList(d2.recent_symptom_distribution), '#0ea5e9');
      renderKpiCards('portrait-high-risk-kpi', [
        { name: '低风险人数', value: ((res.high_risk_summary || {}).low || 0) + '人' },
        { name: '中风险人数', value: ((res.high_risk_summary || {}).medium || 0) + '人' },
        { name: '高风险人数', value: ((res.high_risk_summary || {}).high || 0) + '人' }
      ]);

      renderKpiCards('portrait-habit-kpi', [
        { name: '吸烟占比', value: (d3.smoking_ratio || 0) + '%' },
        { name: '饮酒占比', value: (d3.drinking_ratio || 0) + '%' },
        { name: '睡眠异常占比', value: (d3.sleep_abnormal_ratio || 0) + '%' },
        { name: '睡眠质量差占比', value: (d3.poor_sleep_quality_ratio || 0) + '%' },
        { name: '烟酒叠加占比', value: (d3.smoking_drinking_ratio || 0) + '%' }
      ]);
      renderHorizontalBars('portrait-habit-risk-bars', [
        { name: '吸烟', value: d3.smoking_ratio || 0 },
        { name: '饮酒', value: d3.drinking_ratio || 0 },
        { name: '睡眠异常', value: d3.sleep_abnormal_ratio || 0 },
        { name: '睡眠质量差', value: d3.poor_sleep_quality_ratio || 0 },
        { name: '烟酒叠加', value: d3.smoking_drinking_ratio || 0 }
      ].map(function (item) {
        return { name: item.name, count: item.value };
      }), '#6366f1', { valueSuffix: '%', maxItems: 5 });
      renderHorizontalBars('portrait-exercise-top10', toList(d3.exercise_top10), '#16a085');
      renderHorizontalBars('portrait-needs-top10', toList(d3.health_needs_top10), '#2980b9');
      renderServiceFunnelCards('portrait-service-funnel', toList((res.dimension4 || {}).service_funnel));
      renderImprovementStackedBars('portrait-improvement-stacked', toList((res.dimension4 || {}).improvement_matrix));
      portraitImprovementRankingRaw = toList((res.dimension4 || {}).improvement_project_ranking);
      renderImprovementProjectRanking('portrait-improvement-ranking', portraitImprovementRankingRaw, (document.getElementById('portrait-improvement-ranking-sort') || {}).value || 'improvement_rate');
    });
  }

  function renderAgeGenderCompare(elId, list) {
    var box = document.getElementById(elId);
    if (!box) return;
    if (!list.length) {
      box.innerHTML = '<p style="color:#666">暂无数据</p>';
      return;
    }
    var max = Math.max.apply(null, list.map(function (x) { return Math.max(x.male || 0, x.female || 0); }).concat([1]));
    var groups = list.map(function (x) {
      var maleHeight = Math.round(((x.male || 0) * 160) / max);
      var femaleHeight = Math.round(((x.female || 0) * 160) / max);
      return '<div class="vbar-group"><div class="vbar-bars">' +
        '<div class="vbar-item" style="height:' + maleHeight + 'px;background:#8ecbff"><span class="num">' + (x.male || 0) + '</span></div>' +
        '<div class="vbar-item" style="height:' + femaleHeight + 'px;background:#ffb6c1"><span class="num">' + (x.female || 0) + '</span></div>' +
        '</div><div class="vbar-label">' + (x.name || '-') + '</div></div>';
    }).join('');
    box.innerHTML = '<div class="vbar-chart">' + groups + '</div><div class="compare-legend"><span class="male">男性</span><span class="female">女性</span></div>';
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

  function renderHorizontalBars(elId, list, color, options) {
    var box = document.getElementById(elId);
    if (!box) return;
    var config = options || {};
    var rows = toList(list).slice(0, config.maxItems || 10);
    if (!rows.length) {
      box.innerHTML = '<p style="color:#666">暂无数据</p>';
      return;
    }
    var max = Math.max.apply(null, rows.map(function (x) { return x.count || 0; }).concat([1]));
    box.innerHTML = rows.map(function (x) {
      var width = Math.round(((x.count || 0) * 100) / max);
      return '<div class="bar-row"><div class="label">' + (x.name || '-') + '</div><div class="bar-track"><div class="bar-fill" style="width:' + width + '%;background:' + color + '"></div></div><div class="value">' + (x.count || 0) + (config.valueSuffix || '') + '</div></div>';
    }).join('');
  }

  function renderRadarChart(elId, items) {
    var box = document.getElementById(elId);
    if (!box) return;
    var list = toList(items).filter(function (x) { return (x.value || 0) >= 0; });
    if (!list.length) {
      box.innerHTML = '<p style="color:#666">暂无数据</p>';
      return;
    }
    var cx = 170; var cy = 150; var radius = 95;
    var levels = [20, 40, 60, 80, 100];
    var axis = list.map(function (item, idx) {
      var angle = (Math.PI * 2 * idx / list.length) - Math.PI / 2;
      return {
        name: item.name,
        value: Math.max(0, Math.min(100, Number(item.value || 0))),
        x: cx + radius * Math.cos(angle),
        y: cy + radius * Math.sin(angle),
        angle: angle
      };
    });
    var grids = levels.map(function (lv) {
      var r = radius * lv / 100;
      var points = axis.map(function (p) {
        return (cx + r * Math.cos(p.angle)) + ',' + (cy + r * Math.sin(p.angle));
      }).join(' ');
      return '<polygon points="' + points + '" fill="none" stroke="#e2e8f0" stroke-width="1"></polygon>';
    }).join('');
    var spokes = axis.map(function (p) {
      return '<line x1="' + cx + '" y1="' + cy + '" x2="' + p.x + '" y2="' + p.y + '" stroke="#e2e8f0" stroke-width="1"></line>';
    }).join('');
    var valuePoints = axis.map(function (p) {
      var r = radius * p.value / 100;
      return (cx + r * Math.cos(p.angle)) + ',' + (cy + r * Math.sin(p.angle));
    }).join(' ');
    var labels = axis.map(function (p) {
      var lx = cx + (radius + 18) * Math.cos(p.angle);
      var ly = cy + (radius + 18) * Math.sin(p.angle);
      return '<text x="' + lx + '" y="' + ly + '" font-size="11" fill="#475569" text-anchor="middle">' + p.name + ' ' + p.value + '%</text>';
    }).join('');
    box.innerHTML = '<div class="radar-wrap"><svg class="radar-svg" viewBox="0 0 340 300">' + grids + spokes +
      '<polygon points="' + valuePoints + '" fill="rgba(59,130,246,0.25)" stroke="#2563eb" stroke-width="2"></polygon>' + labels + '</svg></div>';
  }

  function renderImprovementHeatmap(elId, list) {
    var box = document.getElementById(elId);
    if (!box) return;
    if (!list.length) {
      box.innerHTML = '<p style="color:#666">暂无数据</p>';
      return;
    }
    var projects = [];
    var parts = [];
    var matrix = {};
    list.forEach(function (item) {
      var project = item.service_project || '未标注项目';
      var part = item.therapy_part || '未标注部位';
      if (projects.indexOf(project) < 0) projects.push(project);
      if (parts.indexOf(part) < 0) parts.push(part);
      if (!matrix[project]) matrix[project] = {};
      matrix[project][part] = item;
    });
    var max = Math.max.apply(null, list.map(function (x) { return x.count || 0; }).concat([1]));
    var thead = '<thead><tr><th>服务项目 \\ 理疗部位</th>' + parts.map(function (part) { return '<th>' + part + '</th>'; }).join('') + '</tr></thead>';
    var tbody = '<tbody>' + projects.map(function (project) {
      var tds = parts.map(function (part) {
        var cell = (matrix[project] || {})[part];
        if (!cell) return '<td>-</td>';
        var ratio = (cell.count || 0) / max;
        var bg = 'rgba(37,99,235,' + (0.12 + ratio * 0.58).toFixed(2) + ')';
        return '<td><div class="heatmap-cell" style="background:' + bg + ';">' + (cell.count || 0) + '人次<br>' + (cell.status_summary || '') + '</div></td>';
      }).join('');
      return '<tr><th>' + project + '</th>' + tds + '</tr>';
    }).join('') + '</tbody>';
    box.innerHTML = '<div class="heatmap-wrap"><table class="heatmap-table">' + thead + tbody + '</table></div>';
  }

  function renderImprovementStackedBars(elId, list) {
    var box = document.getElementById(elId);
    if (!box) return;
    if (!list.length) {
      box.innerHTML = '<p style="color:#666">暂无数据</p>';
      return;
    }
    var statusOrder = ['无改善', '部分改善', '明显改善', '加重'];
    var statusColors = {
      '无改善': '#94a3b8',
      '部分改善': '#60a5fa',
      '明显改善': '#22c55e',
      '加重': '#ef4444'
    };
    var buckets = {};
    list.forEach(function (item) {
      var project = (item.service_project || '未标注项目').trim() || '未标注项目';
      if (!buckets[project]) {
        buckets[project] = { total: 0, statuses: { '无改善': 0, '部分改善': 0, '明显改善': 0, '加重': 0 } };
      }
      buckets[project].total += Number(item.count || 0);
      var summary = String(item.status_summary || '');
      statusOrder.forEach(function (status) {
        var reg = new RegExp(status + '(\\d+)');
        var matched = summary.match(reg);
        if (matched) buckets[project].statuses[status] += Number(matched[1] || 0);
      });
    });
    var rows = Object.keys(buckets).map(function (project) {
      var row = buckets[project];
      return { project: project, total: row.total, statuses: row.statuses };
    }).sort(function (a, b) { return b.total - a.total; });
    var legend = '<div class="stacked-legend">' + statusOrder.map(function (status) {
      return '<span style="--color:' + statusColors[status] + ';">' + status + '</span>';
    }).join('') + '</div>';
    var listHtml = '<div class="stacked-chart">' + rows.map(function (row) {
      var segments = statusOrder.map(function (status) {
        var value = Number(row.statuses[status] || 0);
        var width = row.total ? ((value * 100) / row.total) : 0;
        return '<div class="stacked-segment" style="width:' + width.toFixed(2) + '%;background:' + statusColors[status] + '" title="' + status + '：' + value + '"></div>';
      }).join('');
      return '<div class="stacked-row"><div class="stacked-label">' + escapeHtml(row.project) + '</div><div class="stacked-track">' + segments + '</div><div class="stacked-value">' + row.total + '</div></div>';
    }).join('') + '</div>';
    box.innerHTML = legend + listHtml;
  }

  function renderImprovementProjectRanking(elId, list, sortBy) {
    var box = document.getElementById(elId);
    if (!box) return;
    var rows = toList(list).slice();
    if (!rows.length) {
      box.innerHTML = '<p style="color:#666">暂无排行榜数据</p>';
      return;
    }
    var mode = sortBy === 'total_services' ? 'total_services' : 'improvement_rate';
    rows.sort(function (a, b) {
      if (mode === 'total_services') {
        if ((b.total_services || 0) !== (a.total_services || 0)) return (b.total_services || 0) - (a.total_services || 0);
        if ((b.improvement_rate || 0) !== (a.improvement_rate || 0)) return (b.improvement_rate || 0) - (a.improvement_rate || 0);
      } else {
        if ((b.improvement_rate || 0) !== (a.improvement_rate || 0)) return (b.improvement_rate || 0) - (a.improvement_rate || 0);
        if ((b.total_services || 0) !== (a.total_services || 0)) return (b.total_services || 0) - (a.total_services || 0);
      }
      return String(a.service_project || '').localeCompare(String(b.service_project || ''), 'zh-CN');
    });
    var maxRate = Math.max.apply(null, rows.map(function (item) { return Number(item.improvement_rate_percent || 0); }).concat([1]));
    var thead = '<thead><tr><th style="width:56px">排名</th><th>服务项目</th><th style="width:100px">总服务次数</th><th style="width:90px">明显改善</th><th style="width:90px">部分改善</th><th style="width:90px">无改善</th><th style="width:80px">加重</th><th style="min-width:220px">改善率</th></tr></thead>';
    var tbody = '<tbody>' + rows.map(function (item, idx) {
      var percent = Number(item.improvement_rate_percent || 0);
      var width = Math.round((percent * 100) / maxRate);
      return '<tr>' +
        '<td>' + (idx + 1) + '</td>' +
        '<td>' + escapeHtml(item.service_project || '未标注项目') + '</td>' +
        '<td>' + (item.total_services || 0) + '</td>' +
        '<td>' + (item.obvious_improved_count || 0) + '</td>' +
        '<td>' + (item.partial_improved_count || 0) + '</td>' +
        '<td>' + (item.no_improved_count || 0) + '</td>' +
        '<td>' + (item.worsen_count || 0) + '</td>' +
        '<td><div class="ranking-progress-track"><div class="ranking-progress-fill" style="width:' + width + '%"></div></div><span class="ranking-progress-text">' + percent.toFixed(1) + '%</span></td>' +
      '</tr>';
    }).join('') + '</tbody>';
    box.innerHTML = '<div class="portrait-ranking-table-wrap"><table class="portrait-ranking-table">' + thead + tbody + '</table></div>';
  }

  function renderServiceFunnelCards(elId, list) {
    var box = document.getElementById(elId);
    if (!box) return;
    if (!list.length) {
      box.innerHTML = '<p style="color:#666">暂无漏斗数据</p>';
      return;
    }
    var max = Math.max.apply(null, list.map(function (item) { return Number(item.count || 0); }).concat([1]));
    box.innerHTML = list.map(function (item, idx) {
      var count = Number(item.count || 0);
      var width = Math.max(32, Math.round((count * 100) / max));
      var ratioText = idx === 0 ? '100%' : ((list[idx - 1] && list[idx - 1].count) ? ((count * 100) / Number(list[idx - 1].count || 1)).toFixed(1) + '%' : '0.0%');
      var arrow = idx === list.length - 1 ? '' : '<div class="funnel-arrow">↓</div>';
      return '<div class="funnel-step">' +
        '<div class="funnel-label">' + escapeHtml(item.label || '-') + '</div>' +
        '<div class="funnel-track"><div class="funnel-bar" style="width:' + width + '%"></div></div>' +
        '<div class="funnel-count">' + count + '人</div>' +
        '<div class="funnel-rate">环比转化：' + ratioText + '</div>' +
      '</div>' + arrow;
    }).join('');
  }

  function getCompanionValue(name) {
    var picked = document.querySelector('input[name="' + name + '"]:checked');
    return picked ? picked.value : '无';
  }

  function setCompanionRadio(name, value) {
    var radios = document.querySelectorAll('input[name="' + name + '"]');
    if (!radios.length) return;
    var found = false;
    radios.forEach(function (radio) {
      var checked = String(radio.value) === String(value || '无');
      radio.checked = checked;
      if (checked) found = true;
    });
    if (!found) radios[0].checked = true;
  }

  function chartColor(idx) {
    var colors = ['#3498db', '#9b59b6', '#1abc9c', '#f39c12', '#e74c3c', '#2ecc71', '#34495e', '#16a085', '#8e44ad', '#d35400'];
    return colors[idx % colors.length];
  }

  document.querySelectorAll('.sidebar a').forEach(function (a) {
    a.addEventListener('click', function (e) { e.preventDefault(); showPage(a.dataset.page); });
  });
  document.querySelectorAll('[data-integrated-tab-btn]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      activeIntegratedTab = btn.getAttribute('data-integrated-tab-btn') || 'basic';
      renderIntegratedTabPanels();
    });
  });
  renderIntegratedTabPanels();
  var btnEquipmentRangeQuery = document.getElementById('btn-equipment-range-query');
  if (btnEquipmentRangeQuery) {
    btnEquipmentRangeQuery.addEventListener('click', function () {
      loadStats();
    });
  }

  document.getElementById('btn-customer-search').addEventListener('click', function () {
    ['customers', 'customerHealth', 'customerAppointments', 'customerHomeAppointments', 'customerImprovement'].forEach(function (k) {
      if (listState[k]) listState[k].page = 1;
    });
    loadCustomers();
  });
  document.getElementById('btn-customer-reset').addEventListener('click', function () {
    document.getElementById('customer-search').value = '';
    ['customers', 'customerHealth', 'customerAppointments', 'customerHomeAppointments', 'customerImprovement'].forEach(function (k) {
      if (listState[k]) listState[k].page = 1;
    });
    loadCustomers();
  });
  document.getElementById('btn-customer-download-all').addEventListener('click', function () {
    var scope = document.getElementById('customer-download-scope').value;
    var search = (document.getElementById('customer-search').value || '').trim();
    if (scope === 'all' && !window.confirm('下载所有客户档案信息')) return;
    get('/api/export/customer-integrated-all?scope=' + encodeURIComponent(scope) + '&search=' + encodeURIComponent(search)).then(function (res) {
      if (!res || res.error) { showMsg('customer-msg', (res && res.error) || '下载失败', true); return; }
      if (res.download_url) window.open(res.download_url, '_blank');
      showMsg('customer-msg', '已触发下载：' + (res.filename || ''));
    });
  });
  document.querySelectorAll('[data-export-form]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var form = btn.dataset.exportForm;
      var limitInput = document.getElementById('export-limit-' + form);
      var limit = limitInput ? parseInt(limitInput.value || '', 10) : '';
      var search = (document.getElementById('customer-search').value || '').trim();
      var url = '/api/export/customer-integrated-form?form=' + encodeURIComponent(form) + '&search=' + encodeURIComponent(search);
      if (limit && limit > 0) url += '&limit=' + encodeURIComponent(limit);
      get(url).then(function (res) {
        if (!res || res.error) { showMsg('customer-msg', (res && res.error) || '下载失败', true); return; }
        if (res.download_url) window.open(res.download_url, '_blank');
        showMsg('customer-msg', '已触发下载：' + (res.filename || ''));
      });
    });
  });

  document.getElementById('btn-health-search').addEventListener('click', function () {
    listState.health.page = 1;
    loadHealthPage();
  });
  document.getElementById('btn-health-reset').addEventListener('click', function () {
    document.getElementById('health-search').value = '';
    listState.health.page = 1;
    loadHealthPage();
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
    var action = pendingAction;
    closeConfirmModal();
    if (typeof action === 'function') action();
  });
  document.getElementById('btn-history-close').addEventListener('click', closeHistoryModal);
  document.addEventListener('click', function (e) {
    closeRowActionMenusExcept(e.target);
  });
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
    if (!body.birth_date) {
      showMsg('customer-msg', '出生日期为必填项', true);
      return;
    }
    body.age = calculateAgeByBirthYear(body.birth_date);
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
  document.getElementById('mc-birth_date').addEventListener('change', function () {
    syncAgeFieldByBirthDate('mc-birth_date', 'mc-age');
  });

  document.getElementById('btn-health-save').addEventListener('click', function () {
    var cid = document.getElementById('health-customer').value;
    var hid = document.getElementById('health-id').value;
    var identityType = healthRadioValue('ha-identity-type');
    var customerBody = {
      name: (document.getElementById('ha-name').value || '').trim(),
      gender: (document.getElementById('ha-gender').value || '').trim(),
      age: (document.getElementById('ha-age').value || '').trim(),
      birth_date: document.getElementById('ha-birth-date').value || null,
      identity_type: identityType,
      military_rank: (document.getElementById('ha-military-rank').value || '').trim(),
      id_card: (document.getElementById('ha-id-card').value || '').trim(),
      phone: (document.getElementById('ha-phone').value || '').trim(),
      address: (document.getElementById('ha-address').value || '').trim(),
      record_creator: (document.getElementById('ha-record-creator').value || '').trim()
    };
    if (!customerBody.name) { showMsg('health-msg', '姓名为必填项', true); return; }
    if (!customerBody.gender) { showMsg('health-msg', '性别为必填项', true); return; }
    if (!customerBody.birth_date) { showMsg('health-msg', '出生日期为必填项', true); return; }
    customerBody.age = calculateAgeByBirthYear(customerBody.birth_date);
    if (!customerBody.identity_type) { showMsg('health-msg', '身份为必选项，请选择“本人”或“家属”', true); return; }
    if (customerBody.id_card && !/^\d{17}[\dXx]$/.test(customerBody.id_card)) { showMsg('health-msg', '身份证号格式不正确，应为18位（最后一位可为X）', true); return; }
    if (!/^\d{11}$/.test(customerBody.phone)) { showMsg('health-msg', '手机号必须为11位数字', true); return; }
    if (!customerBody.record_creator) { showMsg('health-msg', '建档人为必填项', true); return; }
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
      age: customerBody.age,
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
      notes: healthCheckboxValues('ha-special-condition').concat(healthValue('ha-special-condition-other') ? ['其他:' + healthValue('ha-special-condition-other')] : []).join('、')
    };
    function resetHealthPageAfterSave() {
      fillHealthForm({});
      clearHealthEditState();
      document.getElementById('health-search').value = '';
      renderHealthDetail(null);
      loadHealthPage();
      window.scrollTo(0, 0);
    }

    function saveHealthAssessment() {
      if (!hid) {
        post('/api/health-assessments', body).then(function (res) {
          if (res.error) { showMsg('health-msg', res.error, true); return; }
          showMsg('health-msg', res.message);
          resetHealthPageAfterSave();
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
          resetHealthPageAfterSave();
        });
      });
    }

    function saveCustomerThenAssessment(customerId) {
      document.getElementById('health-customer').value = customerId;
      body.customer_id = parseInt(customerId, 10);
      saveHealthAssessment();
    }

    if (cid) {
      put('/api/customers/' + cid, customerBody).then(function (res) {
        if (res.error) { showMsg('health-msg', res.error, true); return; }
        saveCustomerThenAssessment(cid);
      });
      return;
    }

    post('/api/customers', customerBody).then(function (res) {
      if (res.error) { showMsg('health-msg', res.error, true); return; }
      var newCustomerId = res.id || (res.data && res.data.id);
      if (!newCustomerId) { showMsg('health-msg', '客户创建失败，请重试', true); return; }
      saveCustomerThenAssessment(newCustomerId);
    });
  });
  document.getElementById('ha-birth-date').addEventListener('change', function () {
    syncAgeFieldByBirthDate('ha-birth-date', 'ha-age');
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
  document.getElementById('apt-sort').addEventListener('change', function () {
    listState.appointments.page = 1;
    loadAppointmentsPage();
  });
  document.getElementById('apt-status-filter').addEventListener('change', function () {
    listState.appointments.page = 1;
    loadAppointmentsPage();
  });
  document.getElementById('apt-checkin-filter').addEventListener('change', function () {
    listState.appointments.page = 1;
    loadAppointmentsPage();
  });
  document.getElementById('btn-apt-history-search').addEventListener('click', function () {
    listState.appointments.page = 1;
    loadAppointmentsPage();
  });
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
      has_companion: getCompanionValue('apt-has-companion'),
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
      ['家属陪同', body.has_companion || '无'],
      ['时间段', selectedAppointmentSlots.map(function (slot) { return slot.start_time + '-' + slot.end_time; }).join('、')],
      ['设备', selectedAppointmentSlots.map(function (slot) { return slot.equipment_name || ('设备' + (slot.equipment_label || '-')); }).join('、')]
    ];
    openConfirmModal(appointmentEditId ? '确认修改预约后保存记录' : '确认预约信息', rows, function () {
      var bookingGroupId = appointmentEditId ? '' : generateBookingGroupId();
      var requests = selectedAppointmentSlots.map(function (slot) {
        var payload = Object.assign({}, body, {
          booking_group_id: bookingGroupId,
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
      has_companion: getCompanionValue('home-has-companion'),
      notes: document.getElementById('home-notes').value,
      status: 'scheduled'
    };
    if (!body.customer_id || !body.project_id || !body.staff_id || !body.appointment_date || !body.location || !body.contact_phone || !selectedHomeSlots.length) {
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
      ['电话', body.contact_phone || '-'],
      ['家属陪同', body.has_companion || '无']
    ];
    openConfirmModal(homeAppointmentEditId ? '确认修改预约后保存记录' : '确认上门预约信息', rows, function () {
      var bookingGroupId = homeAppointmentEditId ? '' : generateBookingGroupId();
      var requests = selectedHomeSlots.map(function (slot) {
        var payload = Object.assign({}, body, {
          booking_group_id: bookingGroupId,
          start_time: slot.start_time,
          end_time: slot.end_time
        });
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
    setCompanionRadio('home-has-companion', '无');
    document.getElementById('home-customer-search').value = '';
    selectedHomeSlot = null;
    selectedHomeSlots = [];
    homeStaffPanel = null;
    renderHomeSlotPanel();
    renderHomeStaffPanel();
    showMsg('home-msg', '已退出编辑');
  });
  document.getElementById('home-sort').addEventListener('change', function () {
    listState.homeAppointments.page = 1;
    loadHomeAppointmentsPage();
  });
  document.getElementById('home-status-filter').addEventListener('change', function () {
    listState.homeAppointments.page = 1;
    loadHomeAppointmentsPage();
  });
  document.getElementById('home-checkin-filter').addEventListener('change', function () {
    listState.homeAppointments.page = 1;
    loadHomeAppointmentsPage();
  });
  document.getElementById('btn-home-history-search').addEventListener('click', function () {
    listState.homeAppointments.page = 1;
    loadHomeAppointmentsPage();
  });
  document.getElementById('portrait-improvement-ranking-sort').addEventListener('change', function () {
    renderImprovementProjectRanking('portrait-improvement-ranking', portraitImprovementRankingRaw, this.value || 'improvement_rate');
  });
  document.getElementById('btn-portrait-query').addEventListener('click', function () {
    loadPortraitPage();
  });
  document.getElementById('btn-portrait-reset').addEventListener('click', function () {
    var start = document.getElementById('portrait-date-from');
    var end = document.getElementById('portrait-date-to');
    if (start) start.value = '';
    if (end) end.value = '';
    loadPortraitPage();
  });

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

  document.getElementById('btn-improvement-search').addEventListener('click', function () {
    listState.improvement.page = 1;
    loadImprovementTrackingPage();
  });
  document.getElementById('btn-improvement-reset').addEventListener('click', function () {
    ['improvement-filter-customer-name', 'improvement-filter-service-project', 'improvement-filter-status', 'improvement-filter-start', 'improvement-filter-end'].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.value = '';
    });
    listState.improvement.page = 1;
    loadImprovementTrackingPage();
  });
  document.getElementById('btn-improvement-pending').addEventListener('click', function () {
    loadImprovementPendingRecords();
  });
  document.getElementById('btn-improvement-upload-file').addEventListener('click', function () {
    if (improvementViewOnly) return;
    document.getElementById('modal-improvement-upload').classList.remove('hide');
  });
  document.getElementById('btn-improvement-upload-close').addEventListener('click', function () {
    closeImprovementUploadModal();
  });
  document.getElementById('btn-improvement-select-file').addEventListener('click', function () {
    document.getElementById('improvement-upload-input').click();
  });
  document.getElementById('improvement-upload-input').addEventListener('change', function () {
    var file = this.files && this.files[0];
    if (!file) return;
    uploadImprovementFile(file);
  });
  (function initImprovementUploadDropzone() {
    var dropzone = document.getElementById('improvement-upload-dropzone');
    if (!dropzone) return;
    ['dragenter', 'dragover'].forEach(function (evtName) {
      dropzone.addEventListener(evtName, function (e) {
        e.preventDefault();
        e.stopPropagation();
        dropzone.classList.add('dragover');
      });
    });
    ['dragleave', 'drop'].forEach(function (evtName) {
      dropzone.addEventListener(evtName, function (e) {
        e.preventDefault();
        e.stopPropagation();
        dropzone.classList.remove('dragover');
      });
    });
    dropzone.addEventListener('drop', function (e) {
      var file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (!file) return;
      uploadImprovementFile(file);
    });
  })();
  document.getElementById('btn-improvement-cancel').addEventListener('click', function () {
    improvementPendingUploadFile = null;
    setImprovementUploadStatus('', false, false);
    document.getElementById('modal-improvement').classList.add('hide');
  });
  document.getElementById('btn-improvement-save').addEventListener('click', function () {
    if (improvementViewOnly) {
      showMsg('improvement-msg', '查看模式不支持修改，请点击“编辑”按钮进行操作', true);
      return;
    }
    applyImprovementCustomerByInput();
    var payload = {
      service_id: (document.getElementById('improvement-service-id').value || '').trim() || null,
      service_type: (document.getElementById('improvement-service-type').value || 'appointments').trim(),
      customer_id: document.getElementById('improvement-customer').value,
      service_time: normalizeServiceTimeForSave(document.getElementById('improvement-service-time').value),
      service_project: (document.getElementById('improvement-service-project').value || '').trim(),
      pre_service_status: document.getElementById('improvement-pre-service-status').value.trim(),
      service_content: document.getElementById('improvement-service-content').value.trim(),
      post_service_evaluation: document.getElementById('improvement-post-service-evaluation').value.trim(),
      improvement_status: (document.getElementById('improvement-status').value || '').trim(),
      followup_time: (document.getElementById('improvement-followup-time').value || '').trim(),
      followup_date: (document.getElementById('improvement-followup-date').value || '').trim(),
      followup_method: (document.getElementById('improvement-followup-method').value || '').trim()
    };
    if (!payload.customer_id || !payload.service_time || !payload.service_project || !payload.improvement_status) {
      showMsg('improvement-msg', '请填写改善记录必填项', true);
      return;
    }
    payload.customer_id = parseInt(payload.customer_id, 10);
    var id = document.getElementById('improvement-id').value;
    var req = id ? put('/api/improvement-records/' + id, payload) : post('/api/improvement-records', payload);
    req.then(function (ret) {
      if (ret && ret.error) { showMsg('improvement-msg', ret.error, true); return; }
      var savedId = (ret && ret.id) || id || (ret && ret.data && ret.data.id) || document.getElementById('improvement-id').value;
      if (!savedId) {
        showMsg('improvement-msg', '保存成功，但未获取记录ID，无法上传附件', true);
        return;
      }
      document.getElementById('improvement-id').value = String(savedId);
      uploadImprovementFileForRecord(savedId, improvementPendingUploadFile).then(function (uploadResult) {
        if (uploadResult && uploadResult.success === false) {
          showMsg('improvement-msg', (id ? '改善记录已更新，' : '改善记录已新增，') + '附件上传失败：' + (uploadResult.error || '') + '。请重试保存或重新上传。', true);
          return;
        }
        document.getElementById('modal-improvement').classList.add('hide');
        showMsg('improvement-msg', id ? '改善记录已更新' : '改善记录已新增');
        loadImprovementTrackingPage();
      });
    });
  });
  document.getElementById('improvement-customer-search').addEventListener('input', function () {
    renderImprovementCustomerOptions(this.value);
  });
  document.getElementById('improvement-customer-search').addEventListener('change', function () {
    applyImprovementCustomerByInput();
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
  document.getElementById('btn-qe-no-show-refresh').addEventListener('click', loadNoShowTop10Chart);
  document.getElementById('qe-no-show-start').addEventListener('change', loadNoShowTop10Chart);
  document.getElementById('qe-no-show-end').addEventListener('change', loadNoShowTop10Chart);

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

  document.getElementById('btn-audit-search').addEventListener('click', function () {
    listState.auditLogs.page = 1;
    loadAuditLogsPage();
  });
  document.getElementById('btn-audit-reset').addEventListener('click', function () {
    ['audit-start-time', 'audit-end-time', 'audit-operator', 'audit-module', 'audit-action', 'audit-keyword'].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.value = '';
    });
    listState.auditLogs.page = 1;
    loadAuditLogsPage();
  });

  document.getElementById('btn-dm-add').addEventListener('click', function () {
    openDeviceManagementModal('appointment');
  });
  document.getElementById('modal-dm-type').addEventListener('change', function () {
    switchDeviceManagementModalType(this.value);
  });
  document.getElementById('btn-dm-modal-cancel').addEventListener('click', closeDeviceManagementModal);
  document.getElementById('btn-dm-modal-save').addEventListener('click', function () {
    var mode = document.getElementById('modal-dm-type').value === 'home' ? 'home' : 'appointment';
    var projectName = (document.getElementById('modal-dm-project-name').value || '').trim();
    var editId = (document.getElementById('modal-dm-edit-id').value || '').trim();
    if (!projectName) {
      showMsg('dm-msg', '请填写项目名称', true);
      return;
    }
    if (mode === 'appointment') {
      var payload = {
        project_name: projectName,
        equipment_name: (document.getElementById('modal-dm-equipment-name').value || '').trim(),
        equipment_status: document.getElementById('modal-dm-equipment-status').value || 'available',
        equipment_location: (document.getElementById('modal-dm-equipment-location').value || '').trim(),
        equipment_description: (document.getElementById('modal-dm-equipment-description').value || '').trim()
      };
      if (!payload.equipment_name) {
        showMsg('dm-msg', '预约服务项目必须绑定设备，请填写设备名称', true);
        return;
      }
      var req = editId ? put('/api/device-management/appointment-items/' + editId, payload) : post('/api/device-management/appointment-items', payload);
      req.then(function (res) {
        if (res.error) { showMsg('dm-msg', res.error, true); return; }
        showMsg('dm-msg', editId ? '预约服务项目已更新' : '预约服务项目已新增');
        closeDeviceManagementModal();
        fillProjectSelect('apt-project', true, '');
        loadAppointmentSlotPanel(false);
        loadDeviceManagementPage();
      });
      return;
    }
    var homePayload = {
      project_name: projectName,
      staff_name: (document.getElementById('modal-dm-staff-name').value || '').trim()
    };
    if (!homePayload.staff_name) {
      showMsg('dm-msg', '请填写项目服务人员', true);
      return;
    }
    var homeReq = editId ? put('/api/device-management/home-items/' + editId, homePayload) : post('/api/device-management/home-items', homePayload);
    homeReq.then(function (res) {
      if (res.error) { showMsg('dm-msg', res.error, true); return; }
      showMsg('dm-msg', editId ? '上门项目已更新' : '上门项目已新增');
      closeDeviceManagementModal();
      fillProjectSelect('home-project', true, 'home');
      loadHomeSlotPanel(false);
      loadDeviceManagementPage();
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
    document.getElementById('health-customer').value = data.customer_id || '';
    document.getElementById('ha-name').value = data.customer_name || '';
    document.getElementById('ha-gender').value = data.gender || '';
    document.getElementById('ha-birth-date').value = (data.birth_date || '').slice(0, 10);
    document.getElementById('ha-id-card').value = data.id_card || '';
    document.getElementById('ha-phone').value = data.phone || '';
    document.getElementById('ha-record-creator').value = data.record_creator || '';
    document.getElementById('ha-military-rank').value = data.military_rank || '';
    var identityType = String(data.identity_type || '').trim();
    document.getElementById('ha-identity-self').checked = identityType === '本人';
    document.getElementById('ha-identity-family').checked = identityType === '家属';
    document.getElementById('health-date').value = (data.assessment_date || today || '').slice(0, 10);
    document.getElementById('ha-age').value = calculateAgeByBirthYear((data.birth_date || '').slice(0, 10)) || data.age || '';
    document.getElementById('ha-height-cm').value = data.height_cm || '';
    document.getElementById('ha-weight-kg').value = data.weight_kg || '';
    document.getElementById('ha-address').value = data.address || '';
    document.getElementById('ha-allergy-details').value = data.allergy_details || '';
    document.getElementById('ha-smoking-years').value = data.smoking_years || '';
    document.getElementById('ha-drinking-years').value = data.drinking_years || '';
    document.getElementById('ha-recent-symptom-other').value = '';
    document.getElementById('ha-recent-symptom-detail').value = data.recent_symptom_detail || '';
    document.getElementById('ha-life-impact-issue-other').value = '';
    document.getElementById('ha-special-condition-other').value = '';
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
    var specialConditionItems = String(data.notes || '').split('、').filter(Boolean);
    var specialConditionOther = specialConditionItems.filter(function(x){ return x.indexOf('其他:')===0; }).map(function(x){ return x.replace('其他:',''); })[0] || '';
    var specialConditionWithoutOtherText = specialConditionItems.filter(function (x) { return x.indexOf('其他:') !== 0; });
    if (specialConditionOther && specialConditionWithoutOtherText.indexOf('其他') === -1) {
      specialConditionWithoutOtherText.push('其他');
    }
    if (lifeImpactOther && lifeImpactWithoutOtherText.indexOf('其他') === -1) {
      lifeImpactWithoutOtherText.push('其他');
    }
    document.getElementById('ha-diagnosed-disease-other').value = diagnosedOther;
    document.getElementById('ha-family-disease-other').value = familyOther;
    document.getElementById('ha-recent-symptom-other').value = symptomOther;
    document.getElementById('ha-life-impact-issue-other').value = lifeImpactOther;
    document.getElementById('ha-special-condition-other').value = specialConditionOther;
    var checkGroups = { 'health-exercise-method': data.exercise_methods, 'health-need': data.health_needs, 'ha-diagnosed-disease': pastItems.filter(function(x){return x.indexOf('其他:')!==0;}), 'ha-family-disease': familyItems.filter(function(x){return x.indexOf('其他:')!==0;}), 'ha-special-condition': specialConditionWithoutOtherText, 'ha-recent-symptom': symptomItems.filter(function(x){return x.indexOf('其他:')!==0;}), 'ha-life-impact-issue': lifeImpactWithoutOtherText };
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
