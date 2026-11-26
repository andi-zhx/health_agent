(function () {
  "use strict";
  const $ = (id) => document.getElementById(id),
    esc = (v) =>
      String(v == null ? "" : v).replace(
        /[&<>"']/g,
        (c) =>
          ({
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#39;",
          })[c],
      );
  const names = {
    "v2-portrait": "主页",
    "v2-operations": "康养服务运营",
    "v2-effects": "康养效果评估",
    "v2-satisfaction": "满意度与需求",
    "v2-personal": "个人健康档案",
    "v2-reports": "健康管理报告",
  };
  const palette = [
    "#6d9ecb",
    "#58a89d",
    "#a1b9da",
    "#d5ad72",
    "#8a9ac0",
    "#7197a7",
  ];
  const statusColors = {
    明显改善: "#4b9e94",
    部分改善: "#9ac7ba",
    无变化: "#c3cfdb",
    加重: "#d18a77",
    未评价: "#e5eaf0",
    不适用: "#eff2f5",
  };
  let api,
    meta = null,
    current = "v2-portrait",
    cache = null,
    cacheKey = "",
    sequence = 0,
    callbacks = new Map(),
    actionID = 0,
    peopleCache = null,
    personal = null,
    selectedPerson = "",
    trendCodes = null,
    rankMode = "services",
    personMetric = "systolic",
    returnFocus = null;
  const number = (v) => (v == null ? "—" : String(v)),
    percent = (v) => (v == null ? "—" : v + "%");
  function button(label, fn, cls = "v2-btn") {
    const id = String(++actionID);
    callbacks.set(id, fn);
    return (
      '<button type="button" class="' +
      cls +
      '" data-v2-action="' +
      id +
      '">' +
      esc(label) +
      "</button>"
    );
  }
  function message(text) {
    $("v2-message").textContent = text || "";
  }
  function empty(text = "暂无有效记录。完成登记后将在这里展示。") {
    return '<div class="v2-empty">' + esc(text) + "</div>";
  }
  function note(text) {
    return '<div class="v2-note">' + esc(text) + "</div>";
  }
  function tag(text) {
    const cls = [
      "明显改善",
      "部分改善",
      "已复评",
      "已反馈",
      "已完成",
      "已恢复",
      "已跟进",
    ].includes(text)
      ? "good"
      : ["加重", "紧急跟进", "异常"].includes(text)
        ? "bad"
        : ["待处理", "待复评", "待维修", "重点关注", "有不适"].includes(text)
          ? "alert"
          : "";
    return (
      '<span class="v2-tag ' + cls + '">' + esc(text || "未记录") + "</span>"
    );
  }
  function panel(title, subtitle, body, actions = "", cls = "", extra = "") {
    return (
      '<section class="v2-panel ' +
      cls +
      '" ' +
      extra +
      '><div class="v2-panel-head"><div><h2>' +
      esc(title) +
      "</h2>" +
      (subtitle ? '<p class="v2-sub">' + esc(subtitle) + "</p>" : "") +
      "</div>" +
      actions +
      "</div>" +
      body +
      "</section>"
    );
  }
  function title(name, subtitle, actions = "") {
    return (
      '<div class="v2-title-row"><div><div class="v2-eyebrow">静安军休所 · 健康服务管理</div><h1>' +
      esc(name) +
      "</h1><p>" +
      esc(subtitle) +
      '</p></div><div class="v2-toolbar">' +
      actions +
      "</div></div>"
    );
  }
  function kpi(label, value, unit, caption, accent = false) {
    return (
      '<article class="v2-kpi' +
      (accent ? " accent" : "") +
      '"><div class="v2-kpi-label">' +
      esc(label) +
      "</div><strong>" +
      esc(number(value)) +
      "<small>" +
      esc(unit || "") +
      "</small></strong><p>" +
      esc(caption || "") +
      "</p></article>"
    );
  }
  function table(headers, rows, caption = "") {
    return rows.length
      ? '<div class="v2-table-wrap"><table class="v2-table">' +
          (caption ? "<caption>" + esc(caption) + "</caption>" : "") +
          "<thead><tr>" +
          headers.map((h) => "<th>" + esc(h) + "</th>").join("") +
          "</tr></thead><tbody>" +
          rows
            .map(
              (r) =>
                "<tr>" + r.map((c) => "<td>" + c + "</td>").join("") + "</tr>",
            )
            .join("") +
          "</tbody></table></div>"
      : empty();
  }
  function bars(items, total, onClick, colors) {
    if (!items.length) return empty();
    const max = total || Math.max(1, ...items.map((x) => x.count));
    return (
      '<div class="v2-bars">' +
      items
        .map(
          (r, i) =>
            '<div class="v2-bar-row"><span>' +
            (onClick
              ? button(r.name, () => onClick(r), "v2-link")
              : esc(r.name)) +
            '</span><div class="v2-track"><span style="width:' +
            Math.min(100, (r.count / max) * 100) +
            "%;background:" +
            (colors ? colors[i % colors.length] : "#7da6cb") +
            '"></span></div><strong>' +
            number(r.count) +
            "</strong></div>",
        )
        .join("") +
      "</div>"
    );
  }
  function legend(items) {
    return (
      '<div class="v2-legend">' +
      items
        .map(
          (r, i) =>
            '<span><i style="--color:' +
            (r.color || palette[i % palette.length]) +
            '"></i>' +
            esc(r.name) +
            "</span>",
        )
        .join("") +
      "</div>"
    );
  }
  function stacked(items, statuses = Object.keys(statusColors)) {
    if (!items.length) return empty();
    return (
      '<div class="v2-stacks">' +
      items
        .map((r) => {
          const total = statuses.reduce(
            (n, s) => n + (r.distribution[s] || 0),
            0,
          );
          return (
            '<div><div class="v2-stack-name"><span>' +
            esc(r.name) +
            "</span><span>有效评价 n=" +
            r.valid +
            " · " +
            percent(r.rate) +
            '</span></div><div class="v2-stack" role="img" aria-label="' +
            esc(
              r.name +
                "：" +
                statuses
                  .map((s) => s + (r.distribution[s] || 0) + "条")
                  .join("，"),
            ) +
            '">' +
            statuses
              .map(
                (s) =>
                  '<span title="' +
                  esc(s) +
                  " " +
                  (r.distribution[s] || 0) +
                  '条" style="width:' +
                  (total ? ((r.distribution[s] || 0) / total) * 100 : 0) +
                  "%;background:" +
                  statusColors[s] +
                  '"></span>',
              )
              .join("") +
            "</div></div>"
          );
        })
        .join("") +
      "</div>" +
      legend(statuses.map((s) => ({ name: s, color: statusColors[s] })))
    );
  }
  function lines(labels, series, units = "人次", references = []) {
    if (!labels.length || !series.some((s) => s.values.some((v) => v != null)))
      return empty("暂无有效数据；未检测、未复评的点不会补成 0。");
    const W = 600,
      H = 235,
      L = 42,
      R = 18,
      T = 17,
      B = 35;
    const all = series
      .flatMap((s) => s.values.filter((v) => v != null))
      .concat(references.map((r) => r.value));
    const min = Math.min(0, ...all),
      max = Math.max(1, ...all);
    const x = (i) =>
        L + (W - L - R) * (labels.length === 1 ? 0.5 : i / (labels.length - 1)),
      y = (v) => T + (H - T - B) * (1 - (v - min) / (max - min));
    let svg =
      '<svg class="v2-chart" viewBox="0 0 ' +
      W +
      " " +
      H +
      '" role="img" aria-label="' +
      esc(
        units +
          "趋势；" +
          labels
            .map(
              (l, i) =>
                l +
                ": " +
                series.map((s) => s.name + " " + number(s.values[i])).join(","),
            )
            .join(";"),
      ) +
      '">';
    for (let n = 0; n <= 4; n++) {
      let val = min + ((max - min) * n) / 4,
        yy = y(val);
      svg +=
        '<line x1="' +
        L +
        '" y1="' +
        yy +
        '" x2="' +
        (W - R) +
        '" y2="' +
        yy +
        '" stroke="#edf1f6"/><text x="' +
        (L - 8) +
        '" y="' +
        (yy + 3) +
        '" text-anchor="end">' +
        Number(val.toFixed(1)) +
        "</text>";
    }
    labels.forEach((l, i) => {
      if (
        labels.length <= 6 ||
        i % Math.ceil(labels.length / 6) === 0 ||
        i === labels.length - 1
      )
        svg +=
          '<text x="' +
          x(i) +
          '" y="' +
          (H - 10) +
          '" text-anchor="middle">' +
          esc(l) +
          "</text>";
    });
    references.forEach((r) => {
      svg +=
        '<line x1="' +
        L +
        '" x2="' +
        (W - R) +
        '" y1="' +
        y(r.value) +
        '" y2="' +
        y(r.value) +
        '" stroke="#bc9b6c" stroke-dasharray="4 4"/><text x="' +
        (W - R) +
        '" y="' +
        (y(r.value) - 4) +
        '" text-anchor="end">' +
        esc(r.name) +
        " " +
        r.value +
        "</text>";
    });
    series.forEach((s, si) => {
      let segment = [];
      const color = s.color || palette[si % palette.length];
      const flush = () => {
        if (segment.length > 1)
          svg +=
            '<polyline points="' +
            segment.join(" ") +
            '" fill="none" stroke="' +
            color +
            '" stroke-width="2.2"/>';
        segment = [];
      };
      s.values.forEach((v, i) => {
        if (v == null) {
          flush();
          return;
        }
        segment.push(x(i) + "," + y(v));
        svg +=
          '<circle cx="' +
          x(i) +
          '" cy="' +
          y(v) +
          '" r="3" fill="' +
          color +
          '"><title>' +
          esc(labels[i] + " " + s.name + " " + v + " " + units) +
          "</title></circle>";
      });
      flush();
    });
    return (
      '<div class="v2-chart-scroll">' +
      svg +
      "</svg></div>" +
      legend(
        series.map((s, i) => ({
          name: s.name,
          color: s.color || palette[i % palette.length],
        })),
      )
    );
  }
  function grouped(items, keys) {
    if (!items.length) return empty();
    const max = Math.max(
      1,
      ...items.flatMap((r) => keys.map((k) => r[k.key] || 0)),
    );
    return (
      '<div class="v2-bars">' +
      items
        .map(
          (r) =>
            '<div><div class="v2-stack-name"><span>' +
            esc(r.name || r.month) +
            "</span><span>" +
            keys.map((k) => k.label + " " + (r[k.key] || 0)).join(" / ") +
            "</span></div>" +
            keys
              .map(
                (k, i) =>
                  '<div class="v2-track" style="margin:5px 0;height:6px"><span style="width:' +
                  ((r[k.key] || 0) / max) * 100 +
                  "%;background:" +
                  palette[i] +
                  '"></span></div>',
              )
              .join("") +
            "</div>",
        )
        .join("") +
      "</div>" +
      legend(keys.map((k, i) => ({ name: k.label, color: palette[i] })))
    );
  }
  function ring(items, center, caption) {
    const colors = ["#498f9b", "#85b7c0", "#c4d0dc", "#d4b388", "#cd8e83"];
    const total = items.reduce((n, r) => n + r.count, 0);
    let offset = 0;
    return (
      '<div class="v2-ring-wrap"><svg class="v2-ring" viewBox="0 0 140 140" role="img" aria-label="' +
      esc(items.map((r) => r.name + r.count).join("，")) +
      '"><circle cx="70" cy="70" r="53" fill="none" stroke="#edf2f7" stroke-width="12"/>' +
      items
        .map((r, i) => {
          let length = total ? (r.count / total) * 333.009 : 0;
          const arc =
            '<circle cx="70" cy="70" r="53" fill="none" stroke="' +
            colors[i % colors.length] +
            '" stroke-width="12" stroke-dasharray="' +
            length +
            " " +
            (333.009 - length) +
            '" stroke-dashoffset="' +
            -offset +
            '" transform="rotate(-90 70 70)"/>';
          offset += length;
          return arc;
        })
        .join("") +
      '<text x="70" y="69">' +
      esc(center) +
      '</text><text x="70" y="85" class="small">' +
      esc(caption) +
      '</text></svg><div class="v2-ring-key">' +
      items
        .map(
          (r, i) =>
            '<div><i style="background:' +
            colors[i % colors.length] +
            ';width:7px;height:7px;border-radius:2px"></i>' +
            esc(r.name) +
            "<strong>" +
            r.count +
            "</strong></div>",
        )
        .join("") +
      "</div></div>"
    );
  }
  function params() {
    return new URLSearchParams({
      start: $("v2-start").value,
      end: $("v2-end").value,
      age: $("v2-age").value,
      gender: $("v2-gender").value,
      project: $("v2-project").value,
    });
  }
  function period() {
    return $("v2-start").value + " — " + $("v2-end").value;
  }
  function canWrite() {
    return (
      meta &&
      ["admin", "operator", "professional"].includes(meta.user.role) &&
      meta.user.can_view_personal
    );
  }
  function professional() {
    return (
      meta &&
      ["admin", "professional"].includes(meta.user.role) &&
      meta.user.can_view_personal
    );
  }
  function personButton(cid, label = "个人档案") {
    return meta.user.can_view_personal && cid
      ? button(label, () => openPerson(cid), "v2-link")
      : "已脱敏";
  }
  function projectName(code) {
    return (
      (meta.projects.find((p) => p.code === code) || {}).name ||
      "非设备上门 / 历史"
    );
  }
  function goto(page) {
    api.showPage(page);
  }
  function exportURL(kind, format = "report", cid) {
    const q = params();
    q.set("kind", kind);
    if (cid) q.set("customer_id", cid);
    return "/api/v2/" + format + "?" + q;
  }
  function exportButtons(kind) {
    if (!meta.user.can_export) return "";
    return (
      button("查看报告 ↗", () =>
        window.open(exportURL(kind), "_blank", "noopener"),
      ) +
      button("导出 Excel", () => {
        location.href = exportURL(kind, "export");
      })
    );
  }
  function serviceActions(r) {
    if (!canWrite() || r.historical) return "—";
    let controls = "";
    if (r.ref?.startsWith("service:"))
      controls += button("编辑服务", () => serviceForm(r.customer_id, r));
    if (r.project_code && r.status === "completed")
      controls += button(
        PROJECT_BY_CODE_SCREEN(r.project_code) ? "检测记录" : "体验评价",
        () => {
          const ref = r.ref || r.service_ref;
          const rows = PROJECT_BY_CODE_SCREEN(r.project_code)
            ? current === "v2-personal"
              ? personal?.screenings || []
              : cache?.effects.screenings || []
            : current === "v2-personal"
              ? personal?.reviews || []
              : cache?.effects.records || [];
          const found = rows.find((x) => (x.service_ref || x.ref) === ref);
          const record = found
            ? {
                ...r,
                ...found,
                record_id: found.record_id || found.id,
                screening_id: found.screening_id || found.id,
              }
            : r;
          PROJECT_BY_CODE_SCREEN(r.project_code)
            ? screeningForm(record)
            : reviewForm(record);
        },
      );
    else if (
      r.project_code &&
      !PROJECT_BY_CODE_SCREEN(r.project_code) &&
      r.status === "scheduled"
    )
      controls += button("登记基线", () => {
        const found = personal?.reviews.find((x) => x.service_ref === r.ref);
        reviewForm(found ? { ...r, ...found, record_id: found.id } : r);
      });
    return controls || "—";
  }
  function serviceTable(records, actions = true) {
    return table(
      [
        "干部 / 服务编号",
        "项目与渠道",
        "状态 / 完成时间",
        "记录来源",
        ...(actions ? ["操作"] : []),
      ],
      records.map((r) => [
        personButton(r.customer_id, r.person_label || "干部 " + r.customer_id) +
          "<br><small>" +
          esc(r.ref || r.service_ref || "") +
          "</small>",
        esc(projectName(r.project_code)) +
          "<br>" +
          tag(r.channel === "home" ? "上门" : "现场"),
        tag(
          {
            completed: "已完成",
            scheduled: "已预约",
            cancelled: "已取消",
            no_show: "未到场",
          }[r.status] || r.status,
        ) +
          "<br>" +
          esc(r.completed_at || r.scheduled_at),
        esc(r.date_source || r.recorded_by || ""),
        ...(actions ? [serviceActions(r)] : []),
      ]),
    );
  }
  function PROJECT_BY_CODE_SCREEN(code) {
    return ["HEARING", "IMMUNO"].includes(code);
  }
  function showServices(code) {
    const list = cache.operations.service_records.filter(
      (r) => !code || r.project_code === code,
    );
    modal(projectName(code) + " · 服务明细", serviceTable(list));
  }
  function servicePanels(d) {
    let html = "";
    html += panel(
      "设备服务使用排名",
      rankMode === "people"
        ? "各项目独立去重人数；总人数不能直接相加"
        : "六项正式项目 · 完成服务人次",
      bars(
        d.operations.projects
          .map((r) => ({ name: r.name, count: r[rankMode], code: r.code }))
          .sort((a, b) => b.count - a.count),
        null,
        (r) => showServices(r.code),
      ),
      button(
        rankMode === "people" ? "切换人次" : "切换人数",
        () => {
          rankMode = rankMode === "people" ? "services" : "people";
          render();
        },
        "v2-link",
      ),
    );
    html += panel(
      "项目效果评价",
      "康养类有效评价；灰色表示未评价，不等同于无效",
      stacked(d.effects.projects.filter((r) => r.category !== "screening")),
      button("查看评估 ↗", () => goto("v2-effects"), "v2-link"),
    );
    html += panel(
      "管理待办",
      "由登记记录形成，可点击进入处理",
      d.dashboard.todos.length
        ? d.dashboard.todos
            .map(
              (t) =>
                '<div class="v2-todo"><span>' +
                esc(t.name) +
                "</span><div><strong>" +
                t.count +
                "</strong>" +
                button("查看 →", () => goto(t.page), "v2-link") +
                "</div></div>",
            )
            .join("")
        : empty("当前范围暂无待办。资料不足时请先完成登记。"),
      button("意见与需求 ↗", () => goto("v2-satisfaction"), "v2-link"),
    );
    return html;
  }
  function pyramid(rows) {
    const max = Math.max(1, ...rows.flatMap((r) => [r.male, r.female]));
    return (
      '<div class="v2-population" role="img" aria-label="年龄性别分布，包含未知组">' +
      rows
        .map(
          (r) =>
            '<div class="v2-population-row"><span>' +
            esc(r.age) +
            '</span><div class="v2-population-bar male" title="男 ' +
            r.male +
            '"><i style="width:' +
            (r.male / max) * 100 +
            '%"></i></div>' +
            '<strong title="分组总人数">' +
            r.total +
            '</strong><div class="v2-population-bar female" title="女 ' +
            r.female +
            '"><i style="width:' +
            (r.female / max) * 100 +
            '%"></i></div>' +
            '<span class="v2-population-unknown">未知 ' +
            r.unknown +
            "</span></div>",
        )
        .join("") +
      "</div>" +
      legend([
        { name: "男", color: "#75a3ce" },
        { name: "女", color: "#a1bfcd" },
        { name: "中间为总人数，右侧为未知性别", color: "#d9e2eb" },
      ])
    );
  }
  function heatmap(labels, rows) {
    if (!labels.length) return empty();
    return (
      '<div class="v2-table-wrap"><table class="v2-table v2-heatmap"><thead><tr><th>分组 / 有效样本</th>' +
      labels.map((l) => "<th>" + esc(l) + "</th>").join("") +
      "</tr></thead><tbody>" +
      rows
        .map(
          (r) =>
            "<tr><th>" +
            esc(r.name) +
            "<br><small>" +
            esc(r.caption || "") +
            "</small></th>" +
            r.values
              .map(
                (v) =>
                  '<td class="' +
                  (v === 0 ? "quiet" : "") +
                  '" style="background:rgba(76,132,184,' +
                  (v ? Math.min(0.65, 0.08 + v * 0.035) : 0.015) +
                  ')">' +
                  v +
                  "</td>",
              )
              .join("") +
            "</tr>",
        )
        .join("") +
      "</tbody></table></div>"
    );
  }
  function homepage(d) {
    const h = d.health,
      s = d.dashboard.summary,
      p = d.dashboard.previous;
    return (
      title(
        "主页",
        "集中查看干部健康画像、服务工作量、改善反馈与管理待办。",
        exportButtons("portrait") +
          (canWrite()
            ? button("＋ 快速登记", () => serviceForm(), "v2-btn primary")
            : ""),
      ) +
      '<div class="v2-kpis">' +
      kpi("纳入干部", h.population, "人", "年龄 / 性别未知组包含在总数中") +
      kpi(
        "有健康评估",
        h.assessed,
        "人",
        "评估覆盖 " + percent(h.assessment_coverage),
      ) +
      kpi("累计服务", s.services, "人次", "等长上期 " + p.services + " 人次") +
      kpi("实际服务人数", s.people, "人", "跨项目去重 · 上期 " + p.people) +
      kpi(
        "有效评价改善率",
        percent(s.improvement_rate),
        "",
        "有效评价 n=" + s.valid_reviews,
        true,
      ) +
      kpi(
        "总体满意率",
        percent(s.satisfaction_rate),
        "",
        "有效问卷 n=" + s.valid_surveys,
      ) +
      '</div><div class="v2-grid">' +
      panel(
        "年龄与性别",
        "全体纳入人群 · 人口金字塔，包含未知组",
        pyramid(h.demographics),
      ) +
      panel(
        "健康检测概况",
        "按对应指标有效人数计算，未检测不当作正常",
        table(
          ["检测项目", "有效人数", "异常人数", "异常率"],
          h.detection.map((r) => [
            esc(r.name),
            r.valid,
            r.valid ? r.abnormal : "—",
            percent(r.rate),
          ]),
        ),
      ) +
      panel(
        "既往病史",
        "多选按人去重 · 有效分母 " + h.disease_denominator,
        bars(h.diseases, null, (r) => drill("diseases", r.name)),
      ) +
      panel(
        "近期症状",
        "与病史分开统计 · 有效分母 " + h.symptom_denominator,
        bars(h.symptoms, null, (r) => drill("symptoms", r.name)),
      ) +
      panel(
        "年龄 × 健康问题",
        "每行显示纳入人数 n 和病史有效人数；多选可重复归类",
        heatmap(
          h.age_health.labels,
          h.age_health.rows.map((r) => ({
            name: r.age,
            caption: "n=" + r.n + " / 有效 " + r.valid,
            values: r.counts,
          })),
        ),
        "",
        "full",
      ) +
      panel(
        "行为与运动方式",
        "分别展示未知及多选回答",
        "<h3>吸烟情况</h3>" +
          bars(h.behaviors.smoking) +
          "<h3>饮酒情况</h3>" +
          bars(h.behaviors.drinking) +
          "<h3>运动方式</h3>" +
          bars(h.behaviors.exercise) +
          note(
            "运动未回答 " +
              h.behaviors.exercise_unknown +
              " 人。睡眠质量与病史中的长期失眠是不同问题。",
          ),
      ) +
      panel(
        "评估完整度与需求",
        "有效人数 / 应评估人数",
        bars(
          h.completeness.map((r) => ({
            name: r.name + " " + r.valid + "/" + r.expected,
            count: r.valid,
          })),
          h.population,
        ) +
          "<h3>健康需求</h3>" +
          bars(h.needs),
      ) +
      servicePanels(d) +
      "</div>" +
      note(
        h.sampling_note +
          " 本期 " +
          period() +
          "；等长上期 " +
          p.start +
          " 至 " +
          p.end +
          "。" +
          d.cohort_note,
      )
    );
  }
  function maintenanceTable(rows) {
    return table(
      ["设备编号", "故障与状态", "停机 / 恢复", "维修记录", "操作"],
      rows.map((r) => [
        esc(
          (meta.equipment.find((e) => e.equipment_id === r.equipment_id) || {})
            .asset_code || r.equipment_id,
        ),
        esc(r.fault_type) + "<br>" + tag(r.status),
        esc(r.down_at || "未记录") + "<br>" + esc(r.restored_at || "尚未恢复"),
        esc(r.solution || "待处理"),
        canWrite() ? button("更新", () => maintenanceForm(r)) : "—",
      ]),
    );
  }
  function operations(d) {
    const o = d.operations,
      s = o.summary;
    let html = title(
      "康养服务运营",
      "六个核心板块，聚焦真实工作量、设备和上门服务。",
      exportButtons("operations") +
        (canWrite()
          ? button("＋ 快速登记", () => serviceForm(), "v2-btn primary")
          : ""),
    );
    const kpis =
      kpi(
        "预约人次",
        s.bookings,
        "人次",
        "履约分母 " + s.booking_eligible + " · 排除已取消",
      ) +
      kpi("实际服务人数", s.people, "人", "跨项目去重") +
      kpi("累计服务人次", s.services, "人次", "一条完成服务计一次") +
      kpi(
        "预约履约率",
        percent(s.fulfillment),
        "",
        s.booking_completed + " / " + s.booking_eligible,
      ) +
      kpi("人均服务次数", s.per_person, "次", "完成服务人次 / 服务人数") +
      kpi(
        "重复使用率",
        percent(s.repeat_rate),
        "",
        s.repeat_people + " / " + s.people + " 人至少使用两次",
      ) +
      kpi(
        "利用率 / 可用率",
        percent(s.utilization) + " / " + percent(s.availability),
        "",
        "仅有排班时长台账时计算",
      ) +
      kpi("上门服务", s.home_services, "人次", "覆盖 " + s.home_people + " 人");
    html +=
      '<div class="v2-grid">' +
      panel(
        "01  核心运营指标",
        "人数、服务次数与有效分母分开呈现",
        '<div class="v2-kpis ops">' + kpis + "</div>",
        "",
        "full",
        'data-ops-block="1"',
      );
    html += panel(
      "02  各设备服务项目使用情况",
      "六项正式项目 · 完成服务人次",
      bars(
        o.projects
          .map((r) => ({ name: r.name, count: r.services, code: r.code }))
          .sort((x, y) => y.count - x.count),
        null,
        (r) => showServices(r.code),
      ),
      "",
      "",
      'data-ops-block="2"',
    );
    const checked = trendCodes || meta.projects.map((p) => p.code);
    const series = o.projects
      .filter((p) => checked.includes(p.code))
      .map((p) => ({
        name: p.name,
        values: o.months.map((m) => m.projects[p.code]),
        color: palette[meta.projects.findIndex((x) => x.code === p.code)],
      }));
    html += panel(
      "03  各设备月度使用趋势",
      "按自然月汇总，跨月范围完整保留",
      '<div class="v2-legend">' +
        meta.projects
          .map(
            (p, i) =>
              '<label><input type="checkbox" data-trend-code="' +
              p.code +
              '" ' +
              (checked.includes(p.code) ? "checked" : "") +
              '><i style="--color:' +
              palette[i] +
              '"></i>' +
              esc(p.name) +
              "</label>",
          )
          .join("") +
        "</div>" +
        lines(
          o.months.map((m) => m.month),
          series,
        ),
      "",
      "",
      'data-ops-block="3"',
    );
    html += panel(
      "04  各项目使用人数与人次",
      "每项目独立去重；总人数不能按项目相加",
      grouped(o.projects, [
        { key: "people", label: "人数" },
        { key: "services", label: "人次" },
      ]),
      "",
      "",
      'data-ops-block="4"',
    );
    html += panel(
      "05  设备维修及故障记录",
      "停机—维修—恢复使用，保留完整过程",
      bars(o.faults) +
        "<details><summary>查看维修明细（" +
        o.maintenance.length +
        " 条）</summary>" +
        maintenanceTable(o.maintenance) +
        "</details>" +
        note(o.capacity.note),
      canWrite()
        ? '<div class="v2-inline-actions">' +
            button("登记故障", () => maintenanceForm()) +
            (professional() ? button("时长台账", () => capacityForm()) : "") +
            "</div>"
        : "",
      "",
      'data-ops-block="5"',
    );
    html +=
      panel(
        "06  上门服务开展情况",
        "上门是服务渠道，不作为第七项设备",
        grouped(o.home_months, [
          { key: "people", label: "人数" },
          { key: "services", label: "人次" },
        ]) +
          "<details><summary>查看上门服务明细（" +
          o.home_records.length +
          " 条）</summary>" +
          serviceTable(o.home_records) +
          "</details>",
        "",
        "full",
        'data-ops-block="6"',
      ) +
      "</div>" +
      note(
        o.sampling_note +
          " 本期 " +
          o.legacy_date_count +
          " 条历史完成记录使用预约日期作为时间代理。",
      );
    return html;
  }
  function quadrant(projects) {
    const pts = projects.filter(
      (p) => p.category !== "screening" && p.valid >= 5 && p.rate != null,
    );
    if (!pts.length)
      return empty("有效评价 n＜5 的项目暂不进入四象限，避免小样本排名。");
    const max = Math.max(1, ...pts.map((p) => p.services));
    const xs = pts.map((p) => p.services).sort((a, b) => a - b),
      ys = pts.map((p) => p.rate).sort((a, b) => a - b);
    const median = (vals) =>
      vals.length % 2
        ? vals[(vals.length - 1) / 2]
        : (vals[vals.length / 2 - 1] + vals[vals.length / 2]) / 2;
    const mx = median(xs),
      my = median(ys);
    return (
      '<div class="v2-chart-scroll"><svg class="v2-chart" viewBox="0 0 560 275" role="img" aria-label="项目使用人次与自述改善率"><rect x="45" y="20" width="470" height="210" fill="#f7fafc"/><line x1="' +
      (45 + (mx / max) * 450) +
      '" x2="' +
      (45 + (mx / max) * 450) +
      '" y1="20" y2="230" stroke="#b9cbdc" stroke-dasharray="4 4"/><line x1="45" x2="515" y1="' +
      (230 - (my / 100) * 210) +
      '" y2="' +
      (230 - (my / 100) * 210) +
      '" stroke="#b9cbdc" stroke-dasharray="4 4"/><text x="45" y="12">自述改善率 0–100%</text><text x="490" y="257" text-anchor="end">使用人次 →</text>' +
      pts
        .map(
          (p, i) =>
            '<circle cx="' +
            (45 + (p.services / max) * 450) +
            '" cy="' +
            (230 - (p.rate / 100) * 210) +
            '" r="8" fill="' +
            palette[i] +
            '"/><text x="' +
            Math.min(450, 45 + (p.services / max) * 450) +
            '" y="' +
            (218 - (p.rate / 100) * 210) +
            '" text-anchor="end">' +
            esc(p.name) +
            " n=" +
            p.valid +
            "</text>",
        )
        .join("") +
      "</svg></div>" +
      note("参考线为本期项目中位数。仅描述观察性关联，不证明设备治疗效果。")
    );
  }
  function reviewTable(rows) {
    return table(
      ["干部 / 项目", "前后评分", "本人反馈", "跟进", "操作"],
      rows.map((r) => [
        personButton(r.customer_id, r.person_label || "干部 " + r.customer_id) +
          "<br>" +
          esc(projectName(r.project_code)),
        esc(
          r.before_score == null
            ? "未记录"
            : r.before_score + " → " + number(r.after_score),
        ) +
          "<br><small>" +
          esc(r.dimension || "未选择维度") +
          "</small>",
        tag(r.status) +
          (r.legacy_unverified
            ? "<br><small>旧记录待核验：" + esc(r.legacy_status) + "</small>"
            : ""),
        tag(r.followup_status || "待登记") + "<br>" + esc(r.due_date || ""),
        canWrite()
          ? button(r.record_id || r.id ? "编辑 / 复评" : "登记评价", () =>
              reviewForm(r),
            )
          : "—",
      ]),
    );
  }
  function effects(d) {
    const e = d.effects,
      s = e.summary;
    let html = title(
      "康养效果评估",
      "以个人变化为基础，区分未评价、不适用与真实无变化。",
      exportButtons("effects") +
        (canWrite()
          ? button(
              "＋ 阶段复评",
              () => reviewForm(null, "stage"),
              "v2-btn primary",
            )
          : ""),
    );
    html +=
      '<div class="v2-kpis">' +
      kpi(
        "有效评价改善率",
        percent(s.rate),
        "",
        "改善 " + s.improved + " / 有效 " + s.valid,
        true,
      ) +
      kpi("有效评价数", s.valid, "条", "单次评价按服务记录去重") +
      kpi("应评价数", s.applicable, "次", "不适用及检测类不计入") +
      kpi(
        "评价覆盖率",
        percent(s.coverage),
        "",
        s.valid + " / " + s.applicable,
      ) +
      kpi(
        "历史待核验",
        s.legacy_unverified,
        "条",
        "旧默认值不直接进入有效评价",
      ) +
      kpi(
        "阶段复评窗口",
        e.stage_records.length,
        "个",
        "按人 / 项目 / 窗口独立统计",
      ) +
      "</div>";
    html +=
      '<div class="v2-grid">' +
      panel(
        "各项目效果评价",
        "康养及专业服务类；检测类单独展示",
        stacked(e.projects.filter((p) => p.category !== "screening")),
      ) +
      panel(
        "阶段性改善情况",
        "同月同人同项目取期末窗口；单位：人·项目",
        grouped(
          e.stage_months.map((r) => ({ name: r.month, ...r })),
          [
            { key: "improved", label: "改善" },
            { key: "stable", label: "稳定" },
            { key: "worse", label: "加重" },
            { key: "not_reviewed", label: "未复评" },
          ],
        ),
      ) +
      panel(
        "累计使用次数与反馈分布",
        "按评价时点的累计使用次数分组；只表示观察性关联",
        stacked(
          e.usage_groups.map((r) => ({ ...r, rate: null })),
          ["明显改善", "部分改善", "无变化", "加重"],
        ),
      ) +
      panel(
        "项目综合价值参考",
        "使用人次 × 有效评价改善率，展示样本数",
        quadrant(e.projects),
      );
    html += panel(
      "检测筛查项目",
      "听力测试、荧光免疫分析仪不参与改善率排名",
      table(
        ["项目", "服务数", "完成检测", "有效报告", "发现异常", "已跟进"],
        e.screening_summary.map((r) => [
          esc(r.name),
          r.services,
          r.completed,
          r.valid_reports,
          r.abnormal,
          r.followed,
        ]),
      ) +
        "<details><summary>检测报告与跟进记录</summary>" +
        table(
          ["干部", "项目", "报告情况", "专业结论", "跟进", "操作"],
          e.screenings.map((r) => [
            personButton(
              r.customer_id,
              r.person_label || "干部 " + r.customer_id,
            ),
            esc(projectName(r.project_code)),
            tag(r.valid_report ? "有效报告" : "待补充"),
            tag(r.abnormal || "未知"),
            tag(r.followup_status || "待登记"),
            canWrite() ? button("登记 / 跟进", () => screeningForm(r)) : "—",
          ]),
        ) +
        "</details>",
      "",
      "full",
    );
    html +=
      panel(
        "体验与复评明细",
        "点击个人档案可查看本人长期趋势和配对变化",
        reviewTable(
          e.records.filter((r) => !PROJECT_BY_CODE_SCREEN(r.project_code)),
        ) +
          "<details><summary>阶段性复评记录</summary>" +
          reviewTable(e.stage_records) +
          "</details>",
        "",
        "full",
      ) +
      "</div>" +
      note(e.sampling_note);
    return html;
  }
  function taskTable(rows) {
    return table(
      ["意见 / 需求", "类别", "状态", "责任人 / 日期", "处理结果", "操作"],
      rows.map((r) => [
        esc(r.title || "已脱敏"),
        esc(r.category),
        tag(r.status),
        esc(r.owner || "待分配") + "<br>" + esc(r.due_date || "待安排"),
        esc(r.result || "待处理"),
        canWrite() && r.id ? button("处理", () => taskForm(r)) : "—",
      ]),
    );
  }
  function satisfaction(d) {
    const s = d.satisfaction;
    return (
      title(
        "满意度与需求",
        "收集真实回答，让每一条意见都有负责人、有反馈。",
        canWrite()
          ? button("＋ 登记问卷", () => surveyForm(), "v2-btn primary")
          : "",
      ) +
      '<div class="v2-grid">' +
      panel(
        "总体满意度",
        "有效问卷 n=" +
          s.summary.valid +
          " · 未反馈服务对象 " +
          s.summary.not_responded +
          " 人",
        ring(s.distribution, percent(s.summary.rate), "总体满意率") +
          note(
            "问卷覆盖 " +
              s.summary.responded_people +
              " / " +
              s.summary.eligible_people +
              " 人（" +
              percent(s.summary.coverage) +
              "）",
          ),
      ) +
      panel(
        "分维度满意度",
        "统一 1–5 分；未回答不记为 0",
        bars(
          s.dimensions.map((r) => ({
            name: r.name + " · n=" + r.valid,
            count: r.score,
          })),
          5,
        ) +
          note(
            "图中无有效回答的维度显示“—”，没有柱长；数值为该维度有效回答均分。",
          ),
      ) +
      panel(
        "未来需求排名",
        "多选按实际答题人数计算 · 有效 n=" + s.summary.needs_answered,
        bars(s.needs) +
          note("各需求比例使用回答需求题人数为分母，不使用选项总数。"),
      ) +
      panel(
        "意见处理进度",
        "收集 → 核实 → 负责人落实 → 反馈",
        bars(
          ["待处理", "处理中", "已完成", "已反馈"].map((name) => ({
            name,
            count: s.tasks.filter((t) => t.status === name).length,
          })),
        ),
      ) +
      panel(
        "意见与需求处理清单",
        "涉及医疗判断的意见转交专业人员评估",
        taskTable(s.tasks),
        canWrite() ? button("＋ 登记意见", () => taskForm()) : "",
        "full",
      ) +
      "</div>" +
      note(s.sampling_note)
    );
  }
  function personPicker(selected) {
    return (
      '<select id="v2-person-select" class="v2-select-person"><option value="">选择干部档案</option>' +
      (peopleCache || [])
        .map(
          (p) =>
            '<option value="' +
            p.id +
            '" ' +
            (String(p.id) === String(selected) ? "selected" : "") +
            ">" +
            esc(p.name) +
            " · " +
            p.id +
            "</option>",
        )
        .join("") +
      "</select>"
    );
  }
  function personalPage() {
    let html = title(
      "个人健康档案",
      "查看本人检测、服务、前后变化和专业随访；不受群体筛选限制。",
      '<input id="v2-person-search" type="search" placeholder="按姓名或干部编号查找" aria-label="搜索干部">' +
        button("查找", () => searchPeople()) +
        personPicker(selectedPerson),
    );
    if (!meta.user.can_view_personal)
      return html + empty("当前账号未获个人档案访问授权。请联系系统管理员。");
    if (!personal)
      return html + empty("请选择一位干部，查看其获授权的个人健康档案。");
    const p = personal,
      person = p.person,
      assessment = p.assessments[0] || {};
    html +=
      '<div class="v2-person-head"><div class="v2-person-icon">' +
      esc((person.name || "档")[0]) +
      "</div><div><h2>" +
      esc(person.name) +
      "</h2><p>干部编号 " +
      person.id +
      " · " +
      esc(person.gender || "性别未知") +
      " · 出生日期 " +
      esc(person.birth_date || "未记录") +
      '</p></div><div class="v2-person-meta">累计完成服务 ' +
      p.summary.services +
      " 次<br>最近服务 " +
      esc(p.summary.last_service || "暂无") +
      "</div></div>";
    const actions =
      (professional()
        ? button("＋ 个人检测", () => measurementForm(person.id)) +
          button("专业管理分层", () => riskForm(person.id))
        : "") +
      (canWrite()
        ? button("＋ 服务登记", () => serviceForm(person.id), "v2-btn primary")
        : "") +
      (meta.user.can_export
        ? button("个人报告 ↗", () =>
            window.open(
              exportURL("personal", "report", person.id),
              "_blank",
              "noopener",
            ),
          ) +
          button("导出 Excel", () => {
            location.href = exportURL("personal", "export", person.id);
          })
        : "");
    html +=
      '<div class="v2-toolbar" style="margin-bottom:18px">' +
      actions +
      '</div><div class="v2-grid">';
    html += panel(
      "预约与服务明细",
      "可先登记预约和基线，完成服务后再填写评价；历史归档仍可查阅",
      serviceTable(p.services),
      "",
      "full",
    );
    html += panel(
      "本人健康概况",
      "最新健康评估 " + esc(assessment.assessment_date || "尚未登记"),
      '<div class="v2-note">主要病史：' +
        esc(assessment.past_medical_history || "未记录") +
        "<br>近期症状：" +
        esc(assessment.recent_symptoms || "未记录") +
        "<br>专业管理提示：" +
        esc(
          p.risks[0]
            ? p.risks[0].level + " · " + p.risks[0].notes
            : "尚未由专业人员确认",
        ) +
        "</div>",
    );
    html += panel(
      "我的服务总览",
      "包括历史档案；归档项目保留原记录，不进入正式运营排名",
      bars(p.summary.projects),
    );
    const readings = p.measurements.filter((r) => r.metric === personMetric);
    const limits = readings.length ? readings[readings.length - 1] : {};
    const refs = [];
    [
      ["reference_low", "参考下限"],
      ["reference_high", "参考上限"],
      ["target_low", "个人目标下限"],
      ["target_high", "个人目标上限"],
    ].forEach(([k, name]) => {
      if (limits[k] != null) refs.push({ name, value: limits[k] });
    });
    const metricSelect =
      '<select id="v2-metric" aria-label="选择个人健康指标">' +
      Object.entries(meta.metrics)
        .map(
          ([key, item]) =>
            '<option value="' +
            key +
            '" ' +
            (key === personMetric ? "selected" : "") +
            ">" +
            esc(item.name) +
            "</option>",
        )
        .join("") +
      "</select>";
    html += panel(
      "个人健康指标趋势",
      "本人真实检测日期 · " + meta.metrics[personMetric].unit,
      lines(
        readings.map((r) => r.measured_at.slice(5, 16)),
        [
          {
            name: meta.metrics[personMetric].name,
            values: readings.map((r) => r.value),
          },
        ],
        meta.metrics[personMetric].unit,
        refs,
      ) +
        note(
          "参考范围和个人目标仅显示专业人员录入值；未配置时不显示参考线，不叠加群体平均线。",
        ),
      metricSelect,
      "full",
    );
    const pairs = p.reviews.filter((r) => r.before_score != null);
    const dimensions = [...new Set(pairs.map((r) => r.dimension))];
    html += panel(
      "个人服务前后对比",
      "同一服务或阶段配对；0 无困扰，10 非常困扰",
      dimensions.length
        ? dimensions
            .map((dim) => {
              const list = pairs.filter((r) => r.dimension === dim);
              return (
                "<h3>" +
                esc(dim) +
                "</h3>" +
                lines(
                  list.map((r) =>
                    (r.evaluated_at || r.baseline_at || "").slice(5, 10),
                  ),
                  [
                    {
                      name: "基线评分",
                      values: list.map((r) => r.before_score),
                      color: "#91aeca",
                    },
                    {
                      name: "复评评分",
                      values: list.map((r) => r.after_score),
                      color: "#499e95",
                    },
                  ],
                  "分",
                )
              );
            })
            .join("")
        : empty("暂无配对评分，未复评的评分保留为空。"),
    );
    html += panel(
      "随访与阶段复评",
      "下一次复评日期、实际结果与跟进状态",
      table(
        ["项目 / 窗口", "计划复评", "实际评价", "状态"],
        p.reviews.map((r) => [
          esc(projectName(r.project_code)) +
            "<br>" +
            esc(
              r.window_start
                ? r.window_start + " 至 " + r.window_end
                : "单次服务",
            ),
          esc(r.due_date || "待安排"),
          esc(r.evaluated_at || "未复评") + "<br>" + tag(r.status),
          tag(r.followup_status),
        ]),
      ),
      canWrite()
        ? button("新增阶段计划", () =>
            reviewForm({ customer_id: person.id }, "stage"),
          )
        : "",
    );
    html += panel(
      "服务与检测时间轴",
      "服务项目、检测报告、异常记录及专业意见",
      p.timeline.length
        ? '<div class="v2-timeline">' +
            p.timeline
              .map(
                (r) =>
                  '<article class="v2-event"><time>' +
                  esc(r.date) +
                  "</time><h4>" +
                  esc(r.type) +
                  " · " +
                  esc(r.title) +
                  "</h4><p>" +
                  esc(r.detail || "暂无补充说明") +
                  (r.recorded_by ? " · 记录人 " + esc(r.recorded_by) : "") +
                  "</p></article>",
              )
              .join("") +
            "</div>"
        : empty(),
    );
    html += panel(
      "检测记录与专业跟进",
      "检测结论单独标注，不纳入康养改善率",
      table(
        ["项目", "报告", "结论", "跟进结果"],
        p.screenings.map((r) => [
          esc(projectName(r.project_code)),
          esc(r.report || "待补充"),
          tag(r.abnormal),
          tag(r.followup_status) + "<br>" + esc(r.followup_result || ""),
        ]),
      ),
    );
    html +=
      panel(
        "个人检测明细",
        "仅授权人员可查看及导出",
        table(
          ["时间", "指标 / 单位", "结果", "来源 / 专业意见"],
          p.measurements.map((r) => [
            esc(r.measured_at),
            esc(meta.metrics[r.metric].name) + " / " + esc(r.unit),
            esc(r.value),
            esc(r.source || "未记录来源") + "<br>" + esc(r.opinion || ""),
          ]),
        ),
        "",
        "full",
      ) + "</div>";
    return html;
  }
  function reports() {
    let html = title(
      "健康管理报告",
      "按同一套统计口径生成汇报材料，支持打印 PDF 与 Excel 导出。",
    );
    if (!meta.user.can_export)
      return html + empty("当前账号未获报告及导出授权。");
    const types =
      meta.user.role === "resident"
        ? [
            [
              "personal",
              "个人健康报告",
              "本人检测、服务、配对变化、复评和专业建议。",
            ],
          ]
        : [
            [
              "operations",
              "运营简报",
              "六个核心运营板块：服务工作量、设备使用、月度趋势、人数人次、故障维修和上门服务。",
            ],
            [
              "portrait",
              "群体健康画像",
              "人群结构、病史症状、专业管理分层、行为与健康需求。不含群体平均医学指标。",
            ],
            [
              "effects",
              "康养成效报告",
              "项目评价分布、有效评价样本、阶段复评、检测跟进、满意度与未来需求。",
            ],
            [
              "personal",
              "个人健康报告",
              "本人健康检测、服务记录、前后变化、复评及专业建议。单独检查个人数据授权。",
            ],
          ];
    return (
      html +
      note(
        "当前统计范围：" +
          period() +
          "。可用快捷日期选择周/月/季度/年度对应的自定义范围。",
      ) +
      '<div class="v2-grid" style="margin-top:20px">' +
      types
        .map(
          (t, i) =>
            '<section class="v2-panel v2-report-card"><div class="v2-report-index">0' +
            (i + 1) +
            "</div><h2>" +
            esc(t[1]) +
            "</h2><p>" +
            esc(t[2]) +
            '</p><div class="v2-toolbar">' +
            (t[0] === "personal"
              ? button("选择个人档案 →", () => goto("v2-personal"))
              : exportButtons(t[0])) +
            "</div></section>",
        )
        .join("") +
      "</div>"
    );
  }
  function render() {
    if (!meta) return;
    callbacks.clear();
    let html = "";
    if (current === "v2-personal") html = personalPage();
    else if (current === "v2-reports") html = reports();
    else if (cache) {
      html = (
        {
          "v2-portrait": homepage,
          "v2-operations": operations,
          "v2-effects": effects,
          "v2-satisfaction": satisfaction,
        }[current] || homepage
      )(cache);
    }
    if (meta.demo)
      html =
        '<div class="v2-demo"><strong>虚构演示环境</strong> · 所有案例仅用于体验系统功能，不可作为真实服务业绩或医学疗效证据。</div>' +
        html;
    if (cache && cache.pending_projects && current === "v2-portrait")
      html =
        '<div class="v2-alert">' +
        cache.pending_projects +
        " 个旧项目名称待业务核验，相关历史记录暂未计入六项正式项目统计。" +
        (meta.user.role === "admin"
          ? button("核验项目", catalogModal, "v2-link")
          : "请联系管理员核验。") +
        "</div>" +
        html;
    const content = $(current.replace("v2-", "v2-") + "-content");
    if (content)
      content.innerHTML =
        html +
        '<footer class="v2-footer"><span>以个人健康追踪为核心 · 所有指标保留有效分母</span><span>SMART CARE / V2.0</span></footer>';
  }
  function loadSnapshot(force = false) {
    const key = params().toString(),
      version = ++sequence;
    if (!force && cache && cacheKey === key) {
      render();
      return Promise.resolve();
    }
    message("");
    const box = $(current + "-content");
    if (box) box.innerHTML = empty("正在汇总业务记录…");
    return api.get("/api/v2/snapshot?" + key).then((data) => {
      if (version !== sequence) return;
      if (data.error) {
        message(data.error);
        if (box) box.innerHTML = empty("统计加载失败，请检查筛选条件后重试。");
        return;
      }
      cache = data;
      cacheKey = key;
      render();
    });
  }
  function onPage(name) {
    current = name;
    $("v2-page-label").textContent =
      names[name] ||
      {
        customers: "客户档案登记",
        health: "健康评估登记",
        appointments: "现场预约",
        "home-appointments": "上门预约",
        "improvement-tracking": "历史理疗记录与附件",
        "query-export": "原查询导出与备份",
        "device-management": "原设备配置",
        "audit-logs": "系统审计日志",
      }[name] ||
      "业务登记";
    $("v2-filters").classList.toggle(
      "hide",
      !name.startsWith("v2-") ||
        name === "v2-personal" ||
        meta?.user.role === "resident",
    );
    $("app-shell").classList.remove("nav-open");
    $("v2-shade").classList.add("hide");
    message("");
    if (!meta || !name.startsWith("v2-")) return;
    if (name === "v2-personal") {
      $("v2-personal-content").innerHTML = empty("正在加载个人档案…");
      ensurePeople().then(() => {
        if (meta.user.role === "resident")
          openPerson(meta.user.customer_id, false);
        else render();
      });
    } else if (name === "v2-reports") render();
    else loadSnapshot();
  }
  function ensurePeople(force = false) {
    if (peopleCache && !force) return Promise.resolve(peopleCache);
    if (!meta.user.can_view_personal) {
      peopleCache = [];
      return Promise.resolve([]);
    }
    return api.get("/api/v2/people").then((data) => {
      if (data.error) {
        message(data.error);
        peopleCache = [];
      } else peopleCache = data;
      return peopleCache;
    });
  }
  function searchPeople() {
    const term = $("v2-person-search").value;
    api
      .get("/api/v2/people?search=" + encodeURIComponent(term))
      .then((data) => {
        if (data.error) {
          message(data.error);
          return;
        }
        peopleCache = data;
        render();
        $("v2-person-search").value = term;
      });
  }
  function openPerson(cid, navigate = true) {
    selectedPerson = String(cid);
    personal = null;
    if (navigate) {
      current = "v2-personal";
      api.showPage(current);
    }
    return api.get("/api/v2/personal/" + cid).then((data) => {
      if (data.error) {
        message(data.error);
        return;
      }
      personal = data;
      if (current === "v2-personal") render();
    });
  }
  function modal(name, html) {
    returnFocus = document.activeElement;
    $("v2-modal-title").textContent = name;
    $("v2-modal-body").innerHTML = html;
    $("v2-modal").classList.remove("hide");
    $("v2-modal-close").focus();
  }
  function closeModal() {
    $("v2-modal").classList.add("hide");
    if (returnFocus && document.contains(returnFocus)) returnFocus.focus();
  }
  function localNow() {
    const d = new Date();
    return (
      d.getFullYear() +
      "-" +
      String(d.getMonth() + 1).padStart(2, "0") +
      "-" +
      String(d.getDate()).padStart(2, "0") +
      "T" +
      String(d.getHours()).padStart(2, "0") +
      ":" +
      String(d.getMinutes()).padStart(2, "0")
    );
  }
  function inputField(f, values) {
    let value = values[f.name] ?? f.default ?? "";
    if (f.type === "datetime-local")
      value = String(value).replace(" ", "T").slice(0, 16);
    const common =
      'name="' +
      f.name +
      '" id="v2-field-' +
      f.name +
      '" ' +
      (f.required ? "required " : "") +
      (f.readonly ? "readonly " : "");
    let inner = "";
    if (f.type === "select")
      inner =
        "<select " +
        common +
        ">" +
        (f.options || [])
          .map((o) => {
            let [v, label] = Array.isArray(o) ? o : [o, o];
            return (
              '<option value="' +
              esc(v) +
              '" ' +
              (String(value) === String(v) ? "selected" : "") +
              ">" +
              esc(label) +
              "</option>"
            );
          })
          .join("") +
        "</select>";
    else if (f.type === "textarea")
      inner =
        "<textarea " +
        common +
        ' maxlength="' +
        (f.max || 2000) +
        '">' +
        esc(value) +
        "</textarea>";
    else if (f.type === "checks") {
      const selected = Array.isArray(value) ? value : [];
      inner =
        '<div class="v2-checkboxes">' +
        f.options
          .map(
            (o) =>
              '<label><input type="checkbox" name="' +
              f.name +
              '" value="' +
              esc(o) +
              '" ' +
              (selected.includes(o) ? "checked" : "") +
              ">" +
              esc(o) +
              "</label>",
          )
          .join("") +
        "</div>";
    } else
      inner =
        "<input " +
        common +
        ' type="' +
        (f.type || "text") +
        '" value="' +
        esc(value) +
        '" ' +
        (f.min != null ? 'min="' + f.min + '" ' : "") +
        (f.max != null && f.type === "number" ? 'max="' + f.max + '" ' : "") +
        (f.type === "number" ? 'step="' + (f.step || "any") + '" ' : "") +
        (f.placeholder ? 'placeholder="' + esc(f.placeholder) + '"' : "") +
        ">";
    return (
      '<label class="' +
      (f.wide ? "wide" : "") +
      '">' +
      esc(f.label) +
      (f.required ? " *" : "") +
      inner +
      (f.hint ? '<span class="v2-form-hint">' + esc(f.hint) + "</span>" : "") +
      "</label>"
    );
  }
  function form(
    name,
    fields,
    values,
    url,
    method = "post",
    hint = "",
    extra = {},
  ) {
    modal(
      name,
      (hint ? note(hint) : "") +
        '<form id="v2-record-form"><div class="v2-form-grid" style="margin-top:18px">' +
        fields.map((f) => inputField(f, values)).join("") +
        '</div><div id="v2-form-message" class="v2-inline-message" role="status" style="margin-top:15px"></div><div class="modal-actions"><button type="submit" class="v2-btn primary" id="v2-form-save">保存记录</button></div></form>',
    );
    $("v2-record-form").addEventListener("submit", (event) => {
      event.preventDefault();
      const data = { ...extra },
        fd = new FormData(event.target);
      fields.forEach(
        (f) =>
          (data[f.name] =
            f.type === "checks" ? fd.getAll(f.name) : fd.get(f.name)),
      );
      const save = $("v2-form-save");
      save.disabled = true;
      api[method](url, data)
        .then((result) => {
          if (result.error) {
            $("v2-form-message").textContent = result.error;
            return;
          }
          closeModal();
          cache = null;
          cacheKey = "";
          peopleCache = null;
          if (current === "v2-personal" && selectedPerson)
            openPerson(selectedPerson, false);
          else if (current.startsWith("v2-")) loadSnapshot(true);
          message("记录已保存。");
        })
        .finally(() => {
          if (document.contains(save)) save.disabled = false;
        });
    });
  }
  function peopleOptions() {
    return [
      ["", "请选择干部"],
      ...(peopleCache || []).map((p) => [p.id, p.name + " · " + p.id]),
    ];
  }
  function projectOptions(blank = false) {
    return [
      ...(blank ? [["", "非设备上门服务"]] : []),
      ...meta.projects.map((p) => [p.code, p.name]),
    ];
  }
  function equipmentOptions() {
    return [
      ["", "未指定 / 非设备服务"],
      ...meta.equipment.map((e) => [
        e.equipment_id,
        e.asset_code + " · " + e.name,
      ]),
    ];
  }
  const personField = () => ({
    name: "customer_id",
    label: "干部档案",
    type: "select",
    options: peopleOptions(),
    required: true,
  });
  const projectField = (blank = false) => ({
    name: "project_code",
    label: "正式项目",
    type: "select",
    options: projectOptions(blank),
    required: !blank,
  });
  function serviceForm(cid, record = {}) {
    ensurePeople(true).then(() => {
      form(
        "驻场快速登记 · 服务记录",
        [
          personField(),
          projectField(true),
          {
            name: "channel",
            label: "服务方式",
            type: "select",
            options: [
              ["onsite", "现场服务"],
              ["home", "上门服务"],
            ],
          },
          {
            name: "status",
            label: "服务状态",
            type: "select",
            options: [
              ["completed", "已完成"],
              ["scheduled", "已预约"],
              ["cancelled", "已取消"],
              ["no_show", "未到场"],
            ],
          },
          {
            name: "scheduled_at",
            label: "预约 / 开始时间",
            type: "datetime-local",
            required: true,
          },
          {
            name: "completed_at",
            label: "实际完成时间",
            type: "datetime-local",
          },
          {
            name: "duration_minutes",
            label: "实际服务时长（分钟）",
            type: "number",
            min: 1,
            max: 1440,
            step: 1,
          },
          {
            name: "equipment_id",
            label: "设备台账",
            type: "select",
            options: equipmentOptions(),
          },
          { name: "concern", label: "主要诉求 / 非设备上门内容", wide: true },
          {
            name: "notes",
            label: "服务说明与异常记录",
            type: "textarea",
            wide: true,
          },
        ],
        {
          customer_id: typeof cid === "number" ? cid : "",
          project_code: "MOXA",
          channel: "onsite",
          status: "completed",
          scheduled_at: localNow(),
          completed_at: localNow(),
          ...record,
        },
        "/api/v2/services" + (record.ref ? "/" + record.ref.split(":")[1] : ""),
        record.ref ? "put" : "post",
        "先记录服务事实。保存完成后，可在“康养效果评估”分别登记体验评价或检测报告；上门是渠道，同一服务只登记一次。",
      );
    });
  }
  function reviewForm(record, kind = "single") {
    ensurePeople().then(() => {
      const r = record || {};
      kind = r.evaluation_type === "stage" ? "stage" : kind;
      const single = kind === "single";
      const code = r.project_code || "MOXA";
      const values = {
        ...r,
        project_code: code,
        evaluation_type: kind,
        status: [
          "明显改善",
          "部分改善",
          "无变化",
          "加重",
          "未评价",
          "不适用",
        ].includes(r.status)
          ? r.status
          : "未评价",
        baseline_at: r.baseline_at || r.scheduled_at || "",
        evaluated_at: r.evaluated_at || "",
        followup_status: r.followup_status || "待复评",
      };
      const fields = single
        ? []
        : [
            personField(),
            {
              ...projectField(),
              options: projectOptions().filter(
                (p) => !["HEARING", "IMMUNO"].includes(p[0]),
              ),
            },
            {
              name: "window_start",
              label: "评价窗口开始",
              type: "date",
              required: true,
            },
            {
              name: "window_end",
              label: "评价窗口结束",
              type: "date",
              required: true,
            },
          ];
      fields.push(
        {
          name: "dimension",
          label: "评价维度（越低困扰越轻）",
          type: "select",
          options: [["", "未选择"], ...meta.dimensions],
        },
        {
          name: "status",
          label: "本人评价",
          type: "select",
          options: meta.statuses,
        },
        { name: "baseline_at", label: "基线记录时间", type: "datetime-local" },
        {
          name: "before_score",
          label: "基线困扰程度（0–10）",
          type: "number",
          min: 0,
          max: 10,
        },
        {
          name: "evaluated_at",
          label: "实际评价 / 复评时间",
          type: "datetime-local",
        },
        {
          name: "after_score",
          label: "评价后困扰程度（0–10）",
          type: "number",
          min: 0,
          max: 10,
          hint: "未复评请留空，不填 0。",
        },
        {
          name: "adverse",
          label: "异常反应",
          type: "select",
          options: ["未询问", "无不适", "有不适"],
        },
        { name: "adverse_notes", label: "不适表现与处理情况" },
        { name: "due_date", label: "下次复评 / 随访日期", type: "date" },
        {
          name: "followup_status",
          label: "跟进状态",
          type: "select",
          options: ["待复评", "已复评", "无需复评"],
        },
        {
          name: "notes",
          label: "本人主观反馈 / 专业目标说明",
          type: "textarea",
          wide: true,
        },
      );
      const rid = r.record_id || (kind === "stage" ? r.id : null);
      form(
        single ? projectName(code) + " · 体验评价" : "阶段性复评 / 随访",
        fields,
        values,
        "/api/v2/reviews" + (rid ? "/" + rid : ""),
        rid ? "put" : "post",
        "评分只表示本人困扰程度；高压氧仓按专业目标与适应范围记录，不由系统设定疗程。历史评价需核实后重新确认。",
        {
          evaluation_type: kind,
          service_ref: single ? r.service_ref || r.ref : null,
        },
      );
    });
  }
  function screeningForm(r) {
    const rid = r.screening_id;
    form(
      projectName(r.project_code) + " · 检测与跟进",
      [
        {
          name: "completed",
          label: "检测是否完成",
          type: "select",
          options: [
            [0, "未完成"],
            [1, "已完成"],
          ],
        },
        {
          name: "valid_report",
          label: "是否有有效报告",
          type: "select",
          options: [
            [0, "尚无有效报告"],
            [1, "已有有效报告"],
          ],
        },
        {
          name: "abnormal",
          label: "专业判读结论",
          type: "select",
          options: professional() ? ["未知", "未见异常", "异常"] : ["未知"],
          hint: "异常结论由专业人员或管理员填写。",
        },
        {
          name: "followup_status",
          label: "跟进状态",
          type: "select",
          options: ["待跟进", "跟进中", "已跟进", "无需跟进"],
        },
        { name: "due_date", label: "建议复查 / 跟进日期", type: "date" },
        {
          name: "report",
          label: "检测项目、结果及有效报告内容 / 编号",
          type: "textarea",
          max: 10000,
          wide: true,
        },
        {
          name: "professional_opinion",
          label: "专业意见及建议复查说明",
          type: "textarea",
          wide: true,
        },
        {
          name: "followup_result",
          label: "实际跟进结果",
          type: "textarea",
          wide: true,
        },
      ].filter(
        (f) =>
          professional() ||
          !["abnormal", "professional_opinion"].includes(f.name),
      ),
      r,
      "/api/v2/screenings" + (rid ? "/" + rid : ""),
      rid ? "put" : "post",
      "检测筛查不填写改善率。无有效报告不能填写检测异常结论。",
      { service_ref: r.service_ref || r.ref },
    );
  }
  function measurementForm(cid) {
    form(
      "记录个人健康检测",
      [
        {
          name: "metric",
          label: "检测指标",
          type: "select",
          options: Object.entries(meta.metrics).map(([key, item]) => [
            key,
            item.name + " · " + item.unit,
          ]),
          required: true,
        },
        {
          name: "value",
          label: "真实检测结果",
          type: "number",
          required: true,
        },
        {
          name: "measured_at",
          label: "实际检测时间",
          type: "datetime-local",
          required: true,
        },
        { name: "source", label: "检测来源 / 仪器 / 机构", required: true },
        { name: "reference_low", label: "专业参考下限", type: "number" },
        { name: "reference_high", label: "专业参考上限", type: "number" },
        {
          name: "target_low",
          label: "个人管理目标下限（可选）",
          type: "number",
        },
        {
          name: "target_high",
          label: "个人管理目标上限（可选）",
          type: "number",
        },
        {
          name: "report",
          label: "报告编号与记录",
          type: "textarea",
          max: 10000,
          wide: true,
        },
        { name: "opinion", label: "专业意见", type: "textarea", wide: true },
      ],
      { metric: personMetric, measured_at: localNow() },
      "/api/v2/measurements",
      "post",
      "检测结果按原始单位保存；血压的收缩压、舒张压分别录入。参考范围和个体目标只能由专业人员确认。",
      { customer_id: cid },
    );
  }
  function riskForm(cid) {
    form(
      "专业管理分层",
      [
        {
          name: "level",
          label: "管理等级",
          type: "select",
          options: ["常规管理", "重点关注", "紧急跟进"],
          required: true,
        },
        {
          name: "assessed_at",
          label: "确认时间",
          type: "datetime-local",
          required: true,
        },
        {
          name: "notes",
          label: "专业判断依据与管理建议",
          type: "textarea",
          wide: true,
          required: true,
        },
      ],
      { assessed_at: localNow() },
      "/api/v2/risks",
      "post",
      "不自动依据检测值诊断风险；保存时记录当前专业人员账号。",
      { customer_id: cid },
    );
  }
  function surveyForm() {
    ensurePeople().then(() => {
      const fields = [
        personField(),
        {
          name: "answered_at",
          label: "实际回答时间",
          type: "datetime-local",
          required: true,
        },
      ];
      [
        ["overall", "总体满意度"],
        ["attitude", "服务态度"],
        ["guidance", "专业指导"],
        ["device", "设备体验"],
        ["booking", "预约便利性"],
        ["environment", "环境舒适度"],
      ].forEach(([name, label]) =>
        fields.push({
          name,
          label,
          type: "select",
          options: [
            ["", "未回答"],
            [5, "5 · 很满意"],
            [4, "4 · 满意"],
            [3, "3 · 一般"],
            [2, "2 · 不满意"],
            [1, "1 · 很不满意"],
          ],
        }),
      );
      fields.push(
        {
          name: "needs_answered",
          label: "需求题是否已回答",
          type: "select",
          options: [
            [0, "未回答"],
            [1, "已回答（可以暂无需求）"],
          ],
        },
        {
          name: "needs",
          label: "未来需求（多选）",
          type: "checks",
          options: meta.needs,
          wide: true,
        },
        {
          name: "comment",
          label: "具体意见 / 建议",
          type: "textarea",
          wide: true,
        },
      );
      form(
        "满意度与需求问卷",
        fields,
        { answered_at: localNow() },
        "/api/v2/surveys",
        "post",
        "未回答的维度留空。填写意见后自动生成一条待处理任务，避免遗漏。",
      );
    });
  }
  function taskForm(r = {}) {
    ensurePeople().then(() => {
      form(
        "意见与需求处理",
        [
          {
            ...personField(),
            required: false,
            options: [["", "不关联个人"], ...peopleOptions().slice(1)],
          },
          { name: "category", label: "需求分类", required: true },
          {
            name: "title",
            label: "意见或需求内容",
            type: "textarea",
            wide: true,
            required: true,
          },
          {
            name: "status",
            label: "处理状态",
            type: "select",
            options: ["待处理", "处理中", "已完成", "已反馈"],
          },
          { name: "owner", label: "负责人" },
          { name: "due_date", label: "计划完成日期", type: "date" },
          {
            name: "feedback_at",
            label: "实际反馈干部时间",
            type: "datetime-local",
          },
          {
            name: "result",
            label: "处理结果 / 转交专业人员情况",
            type: "textarea",
            wide: true,
          },
        ],
        { category: "服务建议", ...r },
        "/api/v2/tasks" + (r.id ? "/" + r.id : ""),
        r.id ? "put" : "post",
        "已完成须填写结果；已反馈须填写实际反馈时间。",
      );
    });
  }
  function maintenanceForm(r = {}) {
    form(
      "设备故障与维修",
      [
        {
          name: "equipment_id",
          label: "设备编号",
          type: "select",
          options: equipmentOptions().slice(1),
          required: true,
        },
        { name: "fault_type", label: "故障类别", required: true },
        {
          name: "reported_at",
          label: "故障报告时间",
          type: "datetime-local",
          required: true,
        },
        { name: "down_at", label: "实际停机时间", type: "datetime-local" },
        {
          name: "repair_started_at",
          label: "开始维修时间",
          type: "datetime-local",
        },
        {
          name: "repair_finished_at",
          label: "维修完成时间",
          type: "datetime-local",
        },
        { name: "restored_at", label: "恢复使用时间", type: "datetime-local" },
        {
          name: "status",
          label: "处理状态",
          type: "select",
          options: ["待维修", "维修中", "已恢复"],
        },
        {
          name: "solution",
          label: "维修结果与复用说明",
          type: "textarea",
          wide: true,
        },
      ],
      { reported_at: localNow(), status: "待维修", ...r },
      "/api/v2/maintenance" + (r.id ? "/" + r.id : ""),
      r.id ? "put" : "post",
      "未恢复的设备会标记为维修状态。恢复后重新允许预约与服务登记。",
    );
  }
  function capacityForm() {
    form(
      "登记设备可服务时长",
      [
        {
          name: "equipment_id",
          label: "设备编号",
          type: "select",
          options: equipmentOptions().slice(1),
          required: true,
        },
        {
          name: "start_at",
          label: "排班开始",
          type: "datetime-local",
          required: true,
        },
        {
          name: "end_at",
          label: "排班结束",
          type: "datetime-local",
          required: true,
        },
      ],
      {},
      "/api/v2/capacity",
      "post",
      "填入真实可服务时段。同一设备时段不能重叠；只有具备此分母时才计算利用率、可用率。",
    );
  }
  function equipmentForm() {
    form(
      "登记正式设备台账",
      [
        projectField(),
        { name: "asset_code", label: "唯一资产编号", required: true },
        { name: "name", label: "设备名称（含编号）", required: true },
        { name: "model", label: "型号" },
        { name: "location", label: "放置地点" },
        {
          name: "maintenance_days",
          label: "维护周期（天）",
          type: "number",
          min: 1,
          max: 3650,
        },
      ],
      {},
      "/api/v2/admin/equipment",
      "post",
      "设备仅可关联六项正式项目；上门服务不是设备项目。",
    );
  }
  function accountForm(r = {}) {
    ensurePeople().then(() =>
      form(
        "账号与数据授权",
        [
          { name: "username", label: "登录账号", required: true },
          {
            name: "password",
            label: r.id ? "新密码（留空保留）" : "初始密码（至少8位）",
            type: "password",
            required: !r.id,
          },
          {
            name: "role",
            label: "角色",
            type: "select",
            options: Object.entries(meta.roles)
              .filter(([k]) => k !== "admin")
              .map(([k, l]) => [k, l]),
            required: true,
          },
          {
            name: "customer_id",
            label: "绑定本人档案（个人端必填）",
            type: "select",
            options: peopleOptions(),
          },
          {
            name: "can_view_personal",
            label: "个人数据访问授权",
            type: "select",
            options: [
              [0, "不授权"],
              [1, "授权（个人端仅本人）"],
            ],
          },
          {
            name: "can_export",
            label: "报告及导出授权",
            type: "select",
            options: [
              [0, "不授权"],
              [1, "授权"],
            ],
          },
          {
            name: "active",
            label: "账号状态",
            type: "select",
            options: [
              [1, "启用"],
              [0, "停用"],
            ],
          },
        ],
        { role: "manager", active: 1, ...r },
        "/api/v2/admin/accounts" + (r.id ? "/" + r.id : ""),
        r.id ? "put" : "post",
        "管理人员默认查看脱敏统计；驻场人员记录服务，专业人员负责健康判断；个人端只能读取绑定的本人数据。",
      ),
    );
  }
  function accountsModal() {
    api.get("/api/v2/admin/accounts").then((rows) => {
      if (rows.error) {
        message(rows.error);
        return;
      }
      modal(
        "账号与数据授权",
        '<div class="v2-toolbar" style="margin-bottom:15px">' +
          button("＋ 新增账号", () => accountForm(), "v2-btn primary") +
          "</div>" +
          table(
            ["账号", "角色", "个人档案授权", "导出授权", "状态", "操作"],
            rows.map((r) => [
              esc(r.username),
              esc(meta.roles[r.role]),
              r.can_view_personal
                ? "已授权" + (r.customer_id ? " · 本人 " + r.customer_id : "")
                : "未授权",
              r.can_export ? "已授权" : "未授权",
              r.active ? "启用" : "停用",
              button("调整", () => accountForm(r)),
            ]),
          ),
      );
    });
  }
  function catalogModal() {
    api.get("/api/v2/admin/catalog").then((d) => {
      if (d.error) {
        message(d.error);
        return;
      }
      const pending = d.links.filter((r) => r.state === "pending");
      modal(
        "六项项目目录与历史核验",
        note(
          "非白名单项目已退出正式入口；历史记录保留原始编号。附件要求“听力检测仪”与“听力测试”、“太空针灸按摩仪”与“按摩机器人”不得未经业务确认直接合并。",
        ) +
          "<h3>待业务确认的旧名称</h3>" +
          table(
            ["旧名称", "建议正式项目", "状态", "操作"],
            pending.map((r) => [
              esc(r.old_name),
              esc(projectName(r.proposed_code)),
              tag("待核验"),
              button("核验对应关系", () =>
                form(
                  "确认旧项目：" + r.old_name,
                  [{ ...projectField(), required: true }],
                  { project_code: r.proposed_code },
                  "/api/v2/admin/catalog/confirm",
                  "post",
                  "保存即表示你已核实这两个名称是同一业务项目。系统只增加映射，不改写、删除历史服务。",
                  { legacy_project_id: r.legacy_project_id, confirmed: true },
                ),
              ),
            ]),
          ) +
          "<h3>迁移与数量核验</h3>" +
          table(
            ["时间", "版本", "说明", "备份"],
            d.migrations.map((r) => [
              esc(r.created_at),
              esc(r.version),
              esc(r.notes),
              esc(r.backup_path || "本次未变更原库结构"),
            ]),
          ) +
          note(
            "归档主数据 " +
              d.archived_rows +
              " 条；外键检查 " +
              (d.foreign_key_errors.length
                ? "发现 " + d.foreign_key_errors.length + " 项需处理"
                : "通过") +
              "。回滚步骤详见项目 docs/v2-acceptance.md。",
          ),
      );
    });
  }
  function adminModal() {
    modal(
      "管理设置",
      '<div class="v2-grid">' +
        panel(
          "六项正式项目",
          "历史记录先归档、业务确认后对应",
          button("查看迁移与项目核验", catalogModal),
        ) +
        panel(
          "账号与权限",
          "个人端、驻场、专业及管理人员",
          button("管理账号授权", accountsModal),
        ) +
        panel(
          "设备资产台账",
          "新增设备编号与维护周期",
          button("登记设备", equipmentForm),
        ) +
        panel(
          "备份与审计",
          "保留原系统备份及审计功能",
          button("备份与恢复", () => {
            closeModal();
            goto("query-export");
          }) +
            button("操作日志", () => {
              closeModal();
              goto("audit-logs");
            }),
        ) +
        "</div>",
    );
  }
  function drill(domain, label) {
    if (!meta.user.can_view_personal) {
      modal(
        "数据访问授权",
        note("当前账号可查看脱敏群体统计，个人下钻需要单独授权。"),
      );
      return;
    }
    const q = params();
    q.set("domain", domain);
    q.set("label", label);
    api.get("/api/v2/drilldown?" + q).then((rows) => {
      if (rows.error) {
        message(rows.error);
        return;
      }
      modal(
        label + " · 授权档案下钻",
        table(
          ["干部编号", "姓名", "年龄 / 性别", "操作"],
          rows.map((r) => [
            r.id,
            esc(r.name),
            esc(r.age == null ? "未知" : r.age) + " / " + esc(r.gender),
            button("个人档案", () => {
              closeModal();
              openPerson(r.id);
            }),
          ]),
        ),
      );
    });
  }
  function preset() {
    if (!meta) return;
    const end = meta.today;
    const d = new Date(end + "T12:00:00");
    const value = $("v2-preset").value;
    let start = end;
    if (value === "custom") return;
    if (value === "30") d.setDate(d.getDate() - 29);
    if (value === "month") d.setDate(1);
    if (value === "quarter") {
      d.setMonth(Math.floor(d.getMonth() / 3) * 3, 1);
    }
    if (value === "year") {
      d.setMonth(0, 1);
    }
    start =
      d.getFullYear() +
      "-" +
      String(d.getMonth() + 1).padStart(2, "0") +
      "-" +
      String(d.getDate()).padStart(2, "0");
    $("v2-start").value = start;
    $("v2-end").value = end;
  }
  function start() {
    return api.get("/api/v2/meta").then((data) => {
      if (data.error) {
        message(data.error);
        return;
      }
      meta = data;
      cache = null;
      cacheKey = "";
      personal = null;
      selectedPerson = "";
      peopleCache = null;
      trendCodes = null;
      document
        .querySelectorAll('[id^="v2-"][id$="-content"]')
        .forEach((el) => (el.innerHTML = ""));
      $("v2-project").innerHTML =
        '<option value="">全部项目</option>' +
        meta.projects
          .map(
            (p) =>
              '<option value="' + p.code + '">' + esc(p.name) + "</option>",
          )
          .join("");
      $("v2-current-user").textContent =
        meta.user.username + " · " + meta.roles[meta.user.role];
      $("v2-demo-badge").classList.toggle("hide", !meta.demo);
      $("v2-admin-button").classList.toggle("hide", meta.user.role !== "admin");
      $("v2-legacy-tools").classList.toggle(
        "hide",
        ["resident", "manager"].includes(meta.user.role),
      );
      document.querySelectorAll("[data-v2-nav]").forEach((el) => {
        const page = el.dataset.v2Nav;
        el.classList.toggle(
          "hide",
          (meta.user.role === "resident" &&
            !["personal", "reports"].includes(page)) ||
            (page === "reports" && !meta.user.can_export),
        );
      });
      if (meta.demo) $("v2-preset").value = "year";
      preset();
      $("login-screen").classList.add("hide");
      $("app-shell").classList.remove("hide");
      goto(meta.user.role === "resident" ? "v2-personal" : "v2-portrait");
    });
  }
  function restore() {
    api.get("/api/auth/session").then((d) => {
      if (d.authenticated) start();
    });
  }
  function init(bridge) {
    api = bridge;
    document.addEventListener("click", (event) => {
      const b = event.target.closest("[data-v2-action]");
      if (b && !b.disabled) {
        const fn = callbacks.get(b.dataset.v2Action);
        if (fn) fn();
      }
    });
    document.addEventListener("change", (event) => {
      if (event.target.id === "v2-person-select" && event.target.value)
        openPerson(Number(event.target.value), false);
      if (event.target.id === "v2-metric") {
        personMetric = event.target.value;
        render();
      }
      if (event.target.dataset.trendCode) {
        trendCodes = Array.from(
          document.querySelectorAll("[data-trend-code]:checked"),
        ).map((e) => e.dataset.trendCode);
        render();
      }
    });
    $("v2-preset").addEventListener("change", preset);
    ["v2-start", "v2-end"].forEach((id) =>
      $(id).addEventListener("change", () => ($("v2-preset").value = "custom")),
    );
    $("v2-apply").addEventListener("click", () =>
      current === "v2-reports" ? render() : loadSnapshot(true),
    );
    $("v2-admin-button").addEventListener("click", adminModal);
    $("v2-logout").addEventListener("click", () =>
      api.post("/api/auth/logout", {}).then(() => location.reload()),
    );
    $("v2-modal-close").addEventListener("click", closeModal);
    $("v2-menu").addEventListener("click", () => {
      $("app-shell").classList.toggle("nav-open");
      $("v2-shade").classList.toggle("hide");
    });
    $("v2-shade").addEventListener("click", () => {
      $("app-shell").classList.remove("nav-open");
      $("v2-shade").classList.add("hide");
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        closeModal();
        $("app-shell").classList.remove("nav-open");
        $("v2-shade").classList.add("hide");
      }
      if (event.key === "Tab" && !$("v2-modal").classList.contains("hide")) {
        const focusables = Array.from(
          $("v2-modal").querySelectorAll(
            "button,input,select,textarea,a[href]",
          ),
        ).filter((el) => !el.disabled && el.offsetParent !== null);
        const first = focusables[0],
          last = focusables[focusables.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    });
  }
  window.CareV2 = { init, restore, start, onPage };
})();
