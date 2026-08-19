/* AI 短剧工作台前端增强：不依赖 htmx 也能工作 */
(function () {
  "use strict";

  // ---- Flash 自动淡出 ----
  document.querySelectorAll("[data-flash]").forEach(function (el) {
    setTimeout(function () {
      el.style.transition = "opacity 0.8s";
      el.style.opacity = "0";
      setTimeout(function () { el.remove(); }, 900);
    }, 6000);
  });

  // ---- 危险操作确认 ----
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (form && form instanceof HTMLFormElement && form.hasAttribute("data-confirm")) {
      if (!window.confirm(form.getAttribute("data-confirm"))) {
        event.preventDefault();
        return;
      }
    }
    lockSubmitButtons(form);
  });

  // ---- 全局防双击 + 提交 loading（第2轮交互优化） ----
  var BUSY_TEXT = { primary: "处理中…", danger: "执行中…", "": "已提交…" };
  function lockSubmitButtons(form) {
    if (!form || !(form instanceof HTMLFormElement)) return;
    var buttons = form.querySelectorAll('button[type="submit"], button:not([type])');
    buttons.forEach(function (button) {
      if (button.classList.contains("btn")) {
        button.dataset.originalText = button.textContent;
        button.disabled = true;
        var label = button.classList.contains("primary") ? BUSY_TEXT.primary
          : (button.classList.contains("danger") ? BUSY_TEXT.danger : BUSY_TEXT[""]);
        button.textContent = label;
        button.classList.add("btn-busy");
      } else {
        button.disabled = true;
      }
    });
  }
  function unlockSubmitButtons(scope) {
    (scope || document).querySelectorAll("button.btn-busy").forEach(function (button) {
      button.disabled = false;
      button.textContent = button.dataset.originalText || button.textContent;
      button.classList.remove("btn-busy");
    });
  }
  // HTMX 行内操作（取消/重试/优先级）失败或返回后恢复按钮
  document.body.addEventListener("htmx:responseError", function () { unlockSubmitButtons(); });
  document.body.addEventListener("htmx:sendError", function () { unlockSubmitButtons(); });

  // ---- 分镜筛选条件持久化（FR-PROJ-004：返回项目时恢复筛选） ----
  // 先清掉 URL 中的 flash 参数（msg/err），避免刷新重复弹提示、污染筛选记忆
  cleanFlashParams();
  var filterForm = document.querySelector("[data-filter-form]");
  if (filterForm) {
    var projectId = filterForm.getAttribute("data-project-id") || "default";
    var storageKey = "wb_filters_" + projectId;
    if (!window.location.search) {
      var saved = null;
      try { saved = localStorage.getItem(storageKey); } catch (e) { /* ignore */ }
      if (saved) {
        window.location.replace(window.location.pathname + saved);
        return;
      }
    } else {
      persistFilterParams(storageKey);
    }
    // 筛选即时生效：下拉变化自动提交（第3轮交互优化）
    filterForm.querySelectorAll("select").forEach(function (select) {
      select.addEventListener("change", function () { filterForm.submit(); });
    });
  }

  // 任务中心等其它筛选条同样即时生效
  document.querySelectorAll("form.filter-bar:not([data-filter-form]) select").forEach(function (select) {
    select.addEventListener("change", function () { select.closest("form").submit(); });
  });

  function cleanFlashParams() {
    if (!window.location.search) return;
    var params = new URLSearchParams(window.location.search);
    if (!params.has("msg") && !params.has("err")) return;
    params.delete("msg"); params.delete("err");
    var query = params.toString();
    var target = window.location.pathname + (query ? "?" + query : "");
    window.history.replaceState(null, "", target);
    var form = document.querySelector("[data-filter-form]");
    if (form) {
      var id = form.getAttribute("data-project-id") || "default";
      persistFilterParams("wb_filters_" + id);
    }
  }

  function persistFilterParams(storageKey) {
    var params = new URLSearchParams(window.location.search);
    params.delete("msg"); params.delete("err");
    try { localStorage.setItem(storageKey, "?" + params.toString()); } catch (e) { /* ignore */ }
  }

  // ---- 版本对比：同步播放（FR-ASSET-003） ----
  var comparePane = document.querySelector("[data-compare]");
  if (comparePane) {
    var videos = Array.prototype.slice.call(comparePane.querySelectorAll("[data-compare-video]"));
    var syncToggle = document.getElementById("sync-play");
    if (videos.length === 2) {
      var locked = false;
      function syncTime(source, target) {
        if (locked || !syncToggle || !syncToggle.checked) return;
        if (Math.abs(source.currentTime - target.currentTime) > 0.12) {
          locked = true;
          target.currentTime = source.currentTime;
          setTimeout(function () { locked = false; }, 250);
        }
      }
      videos[0].addEventListener("timeupdate", function () { syncTime(videos[0], videos[1]); });
      videos[1].addEventListener("timeupdate", function () { syncTime(videos[1], videos[0]); });
      videos.forEach(function (video) {
        video.addEventListener("play", function () {
          if (syncToggle && syncToggle.checked) {
            videos.forEach(function (other) { if (other !== video) other.play().catch(function () {}); });
          }
        });
        video.addEventListener("pause", function () {
          if (syncToggle && syncToggle.checked) {
            videos.forEach(function (other) { if (other !== video) other.pause(); });
          }
        });
      });
    }
  }

  // ---- 视频循环播放快捷切换（双击循环） ----
  document.addEventListener("dblclick", function (event) {
    var video = event.target;
    if (video instanceof HTMLVideoElement) {
      video.loop = !video.loop;
      video.style.outline = video.loop ? "2px solid var(--accent)" : "none";
    }
  });

  // ---- 媒体全屏预览 Lightbox（第4轮交互优化，FR-ASSET-001） ----
  var lightboxState = { items: [], index: 0, open: false };

  function openLightbox(group, startUrl, isVideo) {
    var items = collectLightboxItems(group);
    var index = Math.max(0, items.findIndex(function (item) { return item.url === startUrl; }));
    lightboxState.items = items.length ? items : [{ url: startUrl, video: isVideo }];
    lightboxState.index = index;
    lightboxState.open = true;
    renderLightbox();
  }

  function collectLightboxItems(group) {
    var selector = group
      ? '[data-lightbox-group="' + group + '"] [data-lightbox]'
      : "[data-lightbox]";
    var found = [];
    document.querySelectorAll(selector).forEach(function (el) {
      var url = el.getAttribute("data-lightbox") || (el instanceof HTMLImageElement ? el.src : "");
      if (url) {
        found.push({
          url: url,
          video: el.getAttribute("data-lightbox-video") === "1" || el.tagName === "VIDEO",
          caption: el.getAttribute("data-lightbox-caption") || "",
        });
      }
    });
    return found;
  }

  function renderLightbox() {
    var overlay = document.getElementById("lightbox-overlay");
    if (!overlay) {
      overlay = document.createElement("div");
      overlay.id = "lightbox-overlay";
      overlay.addEventListener("click", function (event) {
        if (event.target === overlay || event.target.classList.contains("lb-close")) closeLightbox();
      });
      document.body.appendChild(overlay);
    }
    var item = lightboxState.items[lightboxState.index];
    var counter = lightboxState.items.length > 1
      ? (lightboxState.index + 1) + " / " + lightboxState.items.length : "";
    overlay.innerHTML =
      '<button class="lb-close" title="关闭 (Esc)">&times;</button>'
      + (lightboxState.items.length > 1 ? '<button class="lb-nav lb-prev" title="上一个 (←)">&#8249;</button>' : "")
      + (lightboxState.items.length > 1 ? '<button class="lb-nav lb-next" title="下一个 (→)">&#8250;</button>' : "")
      + (item.video
        ? '<video class="lb-media" controls autoplay src="' + item.url + '"></video>'
        : '<img class="lb-media" src="' + item.url + '" alt="">')
      + '<div class="lb-caption">' + (item.caption || "") + '<span class="lb-counter mono">' + counter + "</span></div>";
    overlay.classList.add("open");
    document.body.style.overflow = "hidden";
    var prev = overlay.querySelector(".lb-prev");
    var next = overlay.querySelector(".lb-next");
    if (prev) prev.addEventListener("click", function (e) { e.stopPropagation(); stepLightbox(-1); });
    if (next) next.addEventListener("click", function (e) { e.stopPropagation(); stepLightbox(1); });
  }

  function stepLightbox(delta) {
    var count = lightboxState.items.length;
    if (!count) return;
    lightboxState.index = (lightboxState.index + delta + count) % count;
    renderLightbox();
  }

  function closeLightbox() {
    lightboxState.open = false;
    var overlay = document.getElementById("lightbox-overlay");
    if (overlay) {
      overlay.classList.remove("open");
      overlay.innerHTML = "";
    }
    document.body.style.overflow = "";
  }

  document.addEventListener("click", function (event) {
    var target = event.target.closest ? event.target.closest("[data-lightbox]") : null;
    if (!target) return;
    event.preventDefault();
    var url = target.getAttribute("data-lightbox");
    if (!url) return;
    var groupEl = target.closest("[data-lightbox-group]");
    openLightbox(groupEl ? groupEl.getAttribute("data-lightbox-group") : null, url,
      target.getAttribute("data-lightbox-video") === "1");
  });

  document.addEventListener("keydown", function (event) {
    if (!lightboxState.open) return;
    if (event.key === "Escape") closeLightbox();
    else if (event.key === "ArrowLeft") stepLightbox(-1);
    else if (event.key === "ArrowRight") stepLightbox(1);
  });

  // ---- 结构化提示词包：字段表单 → JSON（第5轮交互优化） ----
  var packageForm = document.getElementById("package-edit-form");
  if (packageForm) {
    packageForm.addEventListener("submit", function () {
      function build(section, arrayFields) {
        var data = {};
        packageForm.querySelectorAll('[name^="f_' + section + '_"]').forEach(function (input) {
          var key = input.name.slice(("f_" + section + "_").length);
          if (arrayFields.indexOf(key) >= 0) {
            data[key] = input.value.split(/[,，]/).map(function (s) { return s.trim(); }).filter(Boolean);
          } else if (input.value.trim() !== "") {
            data[key] = input.value.trim();
          }
        });
        return data;
      }
      packageForm.querySelector('[name="image_json"]').value = JSON.stringify(build("image", ["identity_refs"]));
      packageForm.querySelector('[name="video_json"]').value = JSON.stringify(build("video", []));
      packageForm.querySelector('[name="audio_json"]').value = JSON.stringify(build("audio", []));
    });
  }

  // ---- 活跃任务条：有→无 时自动刷新页面结果（第1轮交互优化） ----
  document.body.addEventListener("htmx:afterSwap", function (event) {
    var bar = event.target;
    if (!(bar instanceof HTMLElement) || bar.id !== "active-jobs-bar") return;
    var projectId = bar.getAttribute("data-project-id") || "";
    var hasActive = !!bar.querySelector(".active-jobs-bar");
    var flagKey = "wb_had_active_jobs_" + projectId;
    var hadActive = false;
    try { hadActive = sessionStorage.getItem(flagKey) === "1"; } catch (e) { /* ignore */ }
    if (hasActive) {
      try { sessionStorage.setItem(flagKey, "1"); } catch (e) { /* ignore */ }
    } else if (hadActive) {
      try { sessionStorage.removeItem(flagKey); } catch (e) { /* ignore */ }
      window.location.reload();
    }
  });
})();
