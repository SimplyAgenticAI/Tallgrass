/* Outlier — reveal animations, count-ups, and the interactive bits. */

(function () {
  "use strict";

  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ------------------------------------------------------------ requests */

  // Every state-changing call carries the session's CSRF token. Wrapping fetch
  // here means a new endpoint cannot forget it and fail in production only.
  var CSRF = (document.querySelector('meta[name="csrf-token"]') || {}).content || "";

  function post(url, body, method) {
    var options = {
      method: method || "POST",
      headers: { "X-CSRF-Token": CSRF }
    };
    if (body !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    return fetch(url, options).then(function (response) {
      if (response.status === 401) {
        window.location.href = "/login";
        throw new Error("Signed out");
      }
      // A 500 returns an HTML error page, not JSON. Parsing that throws a
      // useless "Unexpected token <" — surface the status instead so the real
      // failure is legible rather than swallowed by a generic catch.
      return response.json().catch(function () {
        throw new Error("Server error (" + response.status + ")");
      });
    });
  }

  /* --------------------------------------------------- server-sent events */

  /* Server-sent events arrive in whatever sized pieces the network hands over,
   * so frames are reassembled here rather than assumed to be whole.
   *
   * Lives at this level because both Sage and Write stream. It was defined
   * inside the Sage block, which meant it simply did not exist on any other
   * page — Write called it and got "readEvents is not defined" the moment
   * anybody pressed the button.
   */
  function readEvents(reader, onEvent) {
    var decoder = new TextDecoder();
    var buffer = "";

    function handle(frame) {
      var line = frame.trim();
      if (line.indexOf("data:") !== 0) return;
      try {
        onEvent(JSON.parse(line.slice(5).trim()));
      } catch (error) {
        /* A frame we can't parse is skipped rather than killing the stream. */
      }
    }

    function pump() {
      return reader.read().then(function (chunk) {
        if (chunk.done) return;
        buffer += decoder.decode(chunk.value, { stream: true });
        var frames = buffer.split("\n\n");
        // The last piece may be half a frame — hold it for the next read.
        buffer = frames.pop();
        frames.forEach(handle);
        return pump();
      });
    }

    return pump();
  }

  /* ------------------------------------------------- expired thumbnails */

  /* A post's picture is Facebook's own CDN link, stored as captured and never
   * re-hosted. Those links are SIGNED AND EXPIRE — the query carries an `oe`
   * timestamp — so a post scanned more than a day or two ago points at
   * something that no longer resolves, and the browser renders its broken
   * image icon: a black box with a torn-page glyph in the corner.
   *
   * Nothing handled that, so a normal and expected end-of-life looked exactly
   * like the app being broken. It says what happened instead.
   *
   * Capture phase, because `error` does not bubble — a delegated listener on
   * document only ever sees it on the way down.
   */
  document.addEventListener("error", function (event) {
    var img = event.target;
    if (!img || img.tagName !== "IMG") return;

    var holder = img.closest(".post-thumb, .detail-media");
    if (!holder || holder.classList.contains("is-expired")) return;

    holder.classList.add("is-expired");
    img.remove();

    var note = document.createElement("span");
    note.className = "thumb-gone";
    // The detail page has room for the reason; a 92px card thumbnail does not.
    note.textContent = holder.classList.contains("detail-media")
      ? "This image is no longer available from Facebook — its link expired. "
        + "The post and its numbers are unaffected."
      : "image expired";
    note.title = "Facebook's image links are signed and expire after a day or "
               + "two. The post itself is unaffected.";
    holder.appendChild(note);
  }, true);

  /* ------------------------------------------------------------ toast */

  var toastEl = document.getElementById("toast");
  var toastTimer;

  function toast(message, isError) {
    if (!toastEl) return;
    toastEl.textContent = message;
    toastEl.className = "toast show" + (isError ? " error" : "");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {
      toastEl.className = "toast";
    }, 2800);
  }

  /* ------------------------------------------------------------ count-up */

  function countUp(el) {
    var target = parseFloat(el.dataset.countup);
    if (isNaN(target)) return;

    // Preserve one decimal only when the source value actually had one.
    var decimals = (el.dataset.countup.indexOf(".") !== -1) ? 1 : 0;

    if (reduceMotion) {
      el.textContent = target.toFixed(decimals);
      return;
    }

    // A bigger number takes longer to climb. A 47x and a 1.2x counting at the
    // same speed is the whole reason the feed reads flat — the number that
    // deserves attention should visibly take more work to reach.
    var duration = Math.max(700, Math.min(700 + Math.abs(target) * 17, 1500));
    var start = performance.now();

    function frame(now) {
      var progress = Math.min((now - start) / duration, 1);
      // Ease-out cubic so it decelerates into the final number.
      var eased = 1 - Math.pow(1 - progress, 3);
      el.textContent = (target * eased).toFixed(decimals);
      if (progress < 1) requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }

  /* ------------------------------------------------------------ reveal */

  var revealed = new WeakSet();

  function activate(el) {
    if (revealed.has(el)) return;
    revealed.add(el);
    el.classList.add("in");

    el.querySelectorAll("[data-countup]").forEach(countUp);

    // The badge arc and the scale bar encode the same number, so they run
    // together — the ring sweeping while the bar reaches past the median.
    var RING_CIRCUMFERENCE = 138.2;   // 2 * PI * r, with r = 22 in the SVG
    el.querySelectorAll(".post-badge[data-arc]").forEach(function (badge) {
      var pct = parseFloat(badge.dataset.arc);
      if (isNaN(pct)) return;
      var ring = badge.querySelector(".ring-fill");
      if (!ring) return;
      // Offset shrinks from full circumference to the arc's remainder.
      ring.style.setProperty(
        "--arc",
        (RING_CIRCUMFERENCE * (1 - Math.min(pct, 100) / 100)).toFixed(1)
      );
    });

    // A breakout is the entire point of the product, so it gets a different
    // arrival than a 1.2x post: the bar overruns the median and settles back,
    // and the badge throws off one ring of light as the score lands.
    var isBreakout = el.classList.contains("tier-breakout");

    // Delay so the width transition is visible after the card fades in.
    setTimeout(function () {
      el.querySelectorAll(".scale-fill").forEach(function (bar) {
        bar.style.width = bar.dataset.fill + "%";
      });

      el.querySelectorAll(".scale-over").forEach(function (bar) {
        var target = parseFloat(bar.dataset.over);
        if (isNaN(target)) return;

        if (!isBreakout || reduceMotion) {
          bar.style.width = target + "%";
          return;
        }

        // The bar starts at the median notch (25%), so it can never be wider
        // than the 75% remaining. Clamp the overshoot rather than letting a
        // near-full bar run off the end of its own track.
        var peak = Math.min(target + 3.5, 75);
        bar.style.setProperty("--over-target", target + "%");
        bar.style.setProperty("--over-peak", peak + "%");
        bar.classList.add("surge");
      });
    }, 180);

    if (isBreakout && !reduceMotion) {
      var badge = el.querySelector(".post-badge[data-arc]");
      // Fires as the ring finishes drawing, so the flare reads as the score
      // landing rather than as decoration that happens to be on the page.
      if (badge) setTimeout(function () { badge.classList.add("beat"); }, 1100);
    }
  }

  if ("IntersectionObserver" in window) {
    var observer = new IntersectionObserver(function (entries) {
      var arriving = entries.filter(function (entry) {
        return entry.isIntersecting;
      });

      // IntersectionObserver makes no promise about the order of a batch, so
      // a screenful used to cascade in whatever order the entries happened to
      // arrive in. Sorting by document position is what makes the list read
      // as assembling top-down instead of pieces lighting up at random.
      arriving.sort(function (a, b) {
        var relation = a.target.compareDocumentPosition(b.target);
        return (relation & Node.DOCUMENT_POSITION_FOLLOWING) ? -1 : 1;
      });

      arriving.forEach(function (entry, index) {
        // Stagger within a batch so a screenful cascades instead of popping.
        setTimeout(function () { activate(entry.target); }, index * 55);
        observer.unobserve(entry.target);
      });
    }, { threshold: 0.08, rootMargin: "0px 0px -40px 0px" });

    document.querySelectorAll(".reveal").forEach(function (el) {
      observer.observe(el);
    });

    // Failsafe: .reveal starts at opacity 0, so if the observer never fires
    // (background tab, non-compositing viewport, an observer that silently
    // fails) the page would sit permanently blank. Content visibility must
    // never depend on an animation callback — force anything still hidden.
    setTimeout(function () {
      document.querySelectorAll(".reveal:not(.in)").forEach(activate);
    }, 1200);
  } else {
    document.querySelectorAll(".reveal").forEach(activate);
  }

  // Count-ups outside a .reveal wrapper still need running.
  document.querySelectorAll("[data-countup]").forEach(function (el) {
    if (!el.closest(".reveal")) countUp(el);
  });

  /* ------------------------------------------------------------ write */

  /* Choosing a group. Deliberately OUTSIDE the block below.
   *
   * That block is gated on #write-go, which the template only renders once a
   * group has already been chosen — so the handler never bound on arrival,
   * and the one click that matters most, the first one, did nothing at all.
   *
   * Changing group reloads rather than re-fetching: the hooks, the top posts
   * and the counts all belong to the group, so re-rendering half of them in
   * place is how a page ends up showing one group's hooks above another
   * group's posts.
   */
  var writeGrid = document.querySelector(".write-grid");
  if (writeGrid) {
    writeGrid.querySelectorAll(".group-chip").forEach(function (chip) {
      chip.addEventListener("click", function () {
        if (chip.classList.contains("selected")) return;
        chip.classList.add("is-loading");
        window.location.href = window.location.pathname
                             + "?source_id=" + chip.dataset.sourceId;
      });
    });
  }

  var writeGo = document.getElementById("write-go");
  if (writeGo) {
    var writeStatus = document.getElementById("write-status");
    var writeOutput = document.getElementById("write-output");
    var writeStop = document.getElementById("write-stop");
    var hookInput = document.getElementById("hook-own-input");
    var postPicker = document.getElementById("post-picker");
    var mode = "pattern";
    var chosenHook = "";

    function selectOne(nodes, chosen) {
      nodes.forEach(function (n) { n.classList.toggle("selected", n === chosen); });
    }

    document.querySelectorAll(".mode-card").forEach(function (card) {
      card.addEventListener("click", function () {
        if (card.hasAttribute("disabled")) return;
        mode = card.dataset.mode;
        selectOne(document.querySelectorAll(".mode-card"), card);
        // The list stays visible in both modes. In pattern mode it is the
        // evidence the model is working from; in beat mode the rows become
        // selectable. Hiding it in pattern mode meant Write asked to be
        // trusted with nothing on screen to trust.
        if (postPicker) {
          postPicker.classList.toggle("is-picking", mode === "beat");
          var label = document.getElementById("post-picker-label");
          if (label) {
            label.textContent = mode === "beat"
              ? "Which post are we beating?"
              : "What this is built from";
          }
        }
      });
    });

    document.querySelectorAll(".pick-post").forEach(function (row) {
      row.addEventListener("click", function () {
        if (!postPicker || !postPicker.classList.contains("is-picking")) return;
        selectOne(document.querySelectorAll(".pick-post"), row);
      });
    });

    document.querySelectorAll(".hook-card").forEach(function (card) {
      card.addEventListener("click", function () {
        var already = card.classList.contains("selected");
        selectOne(document.querySelectorAll(".hook-card"), already ? null : card);
        var own = card.classList.contains("hook-own") && !already;
        if (hookInput) {
          hookInput.hidden = !own;
          if (own) hookInput.focus();
        }
        chosenHook = already ? "" : (card.dataset.hook || "");
      });
    });

    function selectedPostId() {
      var row = document.querySelector(".pick-post.selected");
      return row ? row.dataset.postId : null;
    }

    function hookValue() {
      var own = document.querySelector(".hook-card.hook-own.selected");
      if (own && hookInput) return hookInput.value.trim();
      return chosenHook;
    }

    var writeAbort = null;
    // The post being beaten, when it has a graphic worth echoing. Read off the
    // chosen row, so it follows the selection rather than the page.
    var writeEchoPostId = null;

    writeGo.addEventListener("click", function () {
      var steer = document.getElementById("write-steer");
      var body = {
        mode: mode,
        hook: hookValue(),
        instructions: steer ? steer.value.trim() : ""
      };

      if (mode === "beat") {
        var postId = selectedPostId();
        if (!postId) {
          writeStatus.className = "msg-line error";
          writeStatus.textContent = "Pick the post you want to beat.";
          return;
        }
        body.post_id = parseInt(postId, 10);
        body.angles = ["same_hook", "personal", "question"];
        var row = document.querySelector(".pick-post.selected");
        writeEchoPostId = (row && row.dataset.graphicBrief === "1")
          ? row.dataset.postId : null;
      } else {
        body.source_id = parseInt(writeGo.dataset.sourceId, 10);
        writeEchoPostId = null;
      }

      writeGo.disabled = true;
      writeGo.textContent = "Writing…";
      if (writeStop) writeStop.hidden = false;
      writeStatus.className = "msg-line";
      writeStatus.textContent = "Working from what actually won here…";

      var panel = startWriting();
      var count = 0;
      var failure = null;
      writeAbort = new AbortController();

      fetch("/api/write/stream", {
        method: "POST",
        headers: { "X-CSRF-Token": CSRF, "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: writeAbort.signal
      })
        .then(function (response) {
          if (response.status === 401) {
            window.location.href = "/login";
            throw new Error("Signed out");
          }
          if (!response.ok || !response.body) {
            // An error before the stream opens is still JSON.
            return response.json().then(function (data) {
              throw new Error(data.error || "Could not write that");
            }, function () {
              throw new Error("Server error (" + response.status + ")");
            });
          }
          return readEvents(response.body.getReader(), function (event) {
            if (event.type === "lead") {
              panel.setLead(event.text, mode);
            } else if (event.type === "item") {
              count++;
              panel.addItem(event.data, count - 1);
              writeStatus.textContent =
                count + (count === 1 ? " post ready…" : " posts ready…");
            } else if (event.type === "error") {
              failure = event.error;
            }
          });
        })
        .then(function () {
          if (failure) throw new Error(failure);
          if (!count) throw new Error("Nothing came back — try again.");
          writeStatus.className = "msg-line";
          writeStatus.textContent = "";
          toast(count === 1 ? "1 post ready" : count + " posts ready");
        })
        .catch(function (error) {
          if (error.name === "AbortError") {
            // Whatever already arrived is real and stays on screen.
            writeStatus.className = "msg-line";
            writeStatus.textContent = count
              ? "Stopped — kept the " + count + " already written."
              : "Stopped.";
            return;
          }
          if (!count) panel.remove();
          writeStatus.className = "msg-line error";
          writeStatus.textContent = error.message;
        })
        .finally(function () {
          panel.finish();
          writeAbort = null;
          writeGo.disabled = false;
          writeGo.textContent = "Write it";
          if (writeStop) writeStop.hidden = true;
        });
    });

    if (writeStop) {
      writeStop.addEventListener("click", function () {
        if (writeAbort) writeAbort.abort();
      });
    }

    /* The output panel, filled in as posts arrive rather than replaced at the
     * end. Each finished post is appended the moment the server has one. */
    function startWriting() {
      var empty = document.getElementById("write-empty");
      if (empty) empty.remove();
      writeOutput.innerHTML = "";

      var panel = document.createElement("div");
      panel.className = "glass panel reveal in";

      var lead = document.createElement("p");
      lead.className = "why";
      lead.hidden = true;
      panel.appendChild(lead);

      var pending = document.createElement("div");
      pending.className = "thinking";
      pending.innerHTML = "<span></span><span></span><span></span>";
      panel.appendChild(pending);

      writeOutput.appendChild(panel);

      return {
        setLead: function (text, usedMode) {
          lead.hidden = false;
          lead.textContent = "";
          var label = document.createElement("b");
          label.textContent = usedMode === "beat"
            ? "Why the original worked: " : "What wins here: ";
          lead.appendChild(label);
          // textContent — model output is never injected as HTML.
          lead.appendChild(document.createTextNode(text));
        },
        addItem: function (item, index) {
          panel.insertBefore(buildVariant(item, index), pending);
        },
        finish: function () { pending.remove(); },
        remove: function () { panel.remove(); }
      };
    }

    function buildVariant(item, index) {
      var block = document.createElement("div");
      block.className = "variant";
      block.style.animationDelay = "0ms";

      var head = document.createElement("div");
      head.className = "variant-head";
      var name = document.createElement("span");
      name.className = "variant-angle";
      name.textContent = item.angle || item.format || ("Option " + (index + 1));
      head.appendChild(name);

      var copyBtn = document.createElement("button");
      copyBtn.className = "btn btn-ghost";
      copyBtn.type = "button";
      copyBtn.textContent = "Copy";
      copyBtn.addEventListener("click", function () {
        navigator.clipboard.writeText(item.body || "").then(function () {
          toast("Copied");
        });
      });
      head.appendChild(copyBtn);

      /* The same graphic buttons the post page offers.
       *
       * Two doorways reached one engine and each was missing what the other
       * had: post detail had the graphic buttons and no hook picker, Write had
       * the hook picker and no graphic buttons. Which feature you got depended
       * on how you arrived, which is worse than having two pages.
       *
       * The delegated .graphic-btn handler already works on any .variant, so
       * this needs the markup and nothing else.
       */
      var graphic = document.createElement("button");
      graphic.type = "button";
      graphic.className = "graphic-btn";
      graphic.textContent = "Generate graphic";
      graphic.dataset.hook = item.hook || item.body || "";
      graphic.dataset.body = item.body || "";
      head.appendChild(graphic);

      // Only for a specific post we are beating, and only when that post left
      // something to echo.
      if (writeEchoPostId) {
        var echo = document.createElement("button");
        echo.type = "button";
        echo.className = "graphic-btn is-echo";
        echo.textContent = "Same style";
        echo.title = "Make a new graphic in the style of the post you are beating";
        echo.dataset.hook = item.hook || item.body || "";
        echo.dataset.body = item.body || "";
        echo.dataset.likePostId = writeEchoPostId;
        head.appendChild(echo);
      }

      block.appendChild(head);

      if (item.hook) {
        var hookLine = document.createElement("p");
        hookLine.className = "variant-hook";
        hookLine.textContent = item.hook;
        block.appendChild(hookLine);
      }

      var copy = document.createElement("p");
      copy.className = "variant-body";
      copy.textContent = item.body || "";
      block.appendChild(copy);

      if (item.why) {
        var note = document.createElement("p");
        note.className = "fine";
        note.textContent = item.why;
        block.appendChild(note);
      }
      return block;
    }

  }

  /* ---------------------------------------------------- admin: backups */

  var backupNow = document.getElementById("backup-now");
  if (backupNow) {
    var backupMsg = document.getElementById("backup-msg");
    backupNow.addEventListener("click", function () {
      backupNow.disabled = true;
      backupMsg.className = "msg-line";
      backupMsg.textContent = "Taking a snapshot…";
      post("/api/admin/backup")
        .then(function (data) {
          if (!data.ok) throw new Error(data.error || "Backup failed");
          backupMsg.textContent = "Saved " + data.name + ". Reloading…";
          toast("Backup taken");
          window.setTimeout(function () { window.location.reload(); }, 700);
        })
        .catch(function (error) {
          backupMsg.className = "msg-line error";
          backupMsg.textContent = error.message;
        })
        .finally(function () { backupNow.disabled = false; });
    });
  }

  /* ------------------------------------------------ admin: reset links */

  var resetIssue = document.getElementById("reset-issue");
  if (resetIssue) {
    var resetEmail = document.getElementById("reset-email");
    var resetMsg = document.getElementById("reset-issue-msg");

    resetIssue.addEventListener("click", function () {
      var email = (resetEmail.value || "").trim();
      if (!email) {
        resetMsg.className = "msg-line error";
        resetMsg.textContent = "Which account?";
        return;
      }

      resetIssue.disabled = true;
      resetMsg.className = "msg-line";
      resetMsg.textContent = "Generating…";

      post("/api/admin/reset-link", { email: email })
        .then(function (data) {
          if (!data.ok) throw new Error(data.error || "Could not generate a link");

          // The link is shown once and never stored anywhere readable, so it
          // is rendered as selectable text rather than a link — clicking it
          // here would spend it on the admin's own browser.
          resetMsg.className = "msg-line";
          resetMsg.textContent = "";

          var line = document.createElement("div");
          line.appendChild(document.createTextNode(
            "One-time link for " + data.email + ", valid " + data.minutes +
            " minutes. Send it to them, don't open it yourself:"));

          var box = document.createElement("input");
          box.type = "text";
          box.readOnly = true;
          box.value = data.link;
          box.style.cssText =
            "width:100%;margin-top:8px;padding:9px 12px;border-radius:9px;" +
            "background:rgba(6,20,13,0.6);border:1px solid var(--border-lit);" +
            "color:var(--emerald-bright);font-size:12.5px";
          box.addEventListener("focus", function () { box.select(); });

          line.appendChild(box);
          resetMsg.appendChild(line);
          box.focus();
          toast("Reset link generated");
        })
        .catch(function (error) {
          resetMsg.className = "msg-line error";
          resetMsg.textContent = error.message;
        })
        .finally(function () {
          resetIssue.disabled = false;
        });
    });
  }

  /* --------------------------------------------------- view transition */

  // The card you click becomes the page it opens. Cross-document view
  // transitions do the work; all this does is tell the browser which badge
  // on a feed full of them is the one being carried across. Purely additive:
  // where the API is missing the link just navigates, as it always did.
  if (!reduceMotion && window.CSS && CSS.supports &&
      CSS.supports("view-transition-name", "none")) {
    document.addEventListener("click", function (event) {
      var link = event.target.closest('a[href*="/post/"]');
      if (!link) return;

      var card = link.closest(".post-card");
      if (!card) return;
      var badge = card.querySelector(".post-badge");
      if (!badge) return;

      // A name has to be unique across the document while the transition
      // runs, so any badge named by an earlier click is released first.
      document.querySelectorAll("[data-vt-named]").forEach(function (prior) {
        prior.style.viewTransitionName = "";
        prior.removeAttribute("data-vt-named");
      });

      badge.style.viewTransitionName = "post-hero";
      badge.setAttribute("data-vt-named", "");
    });
  }

  /* ------------------------------------------------------------ hover FX */

  // Cursor-tracking spotlight. One delegated listener, coalesced into a single
  // rAF per frame — a page of cards each with its own mousemove handler would
  // drop frames on scroll.
  if (!reduceMotion) {
    var fxTarget = null, fxX = 0, fxY = 0, fxQueued = false;

    function applyFx() {
      fxQueued = false;
      if (!fxTarget) return;

      var rect = fxTarget.getBoundingClientRect();
      var relX = fxX - rect.left;
      var relY = fxY - rect.top;

      // Spotlight position, consumed by a radial-gradient in CSS.
      fxTarget.style.setProperty("--mx", relX + "px");
      fxTarget.style.setProperty("--my", relY + "px");

    }

    document.addEventListener("mousemove", function (event) {
      var target = event.target.closest(".spotlight");

      if (target !== fxTarget) {
        if (fxTarget) fxTarget.classList.remove("fx-on");
        fxTarget = target;
        if (fxTarget) fxTarget.classList.add("fx-on");
      }

      if (!fxTarget) return;
      fxX = event.clientX;
      fxY = event.clientY;
      if (!fxQueued) {
        fxQueued = true;
        requestAnimationFrame(applyFx);
      }
    }, { passive: true });

    // Magnetic buttons: nudge toward the cursor when it's close.
    document.addEventListener("mousemove", function (event) {
      var btn = event.target.closest(".btn-primary");
      if (!btn) {
        document.querySelectorAll(".btn-primary[style*='translate']").forEach(function (b) {
          b.style.transform = "";
        });
        return;
      }
      var rect = btn.getBoundingClientRect();
      var dx = event.clientX - (rect.left + rect.width / 2);
      var dy = event.clientY - (rect.top + rect.height / 2);
      btn.style.transform = "translate(" + (dx * 0.14).toFixed(1) + "px," +
                            (dy * 0.2).toFixed(1) + "px)";
    }, { passive: true });

    document.addEventListener("mouseleave", function (event) {
      var btn = event.target.closest && event.target.closest(".btn-primary");
      if (btn) btn.style.transform = "";
    }, true);
  }

  // A reset navigates away, so its confirmation has to survive the load.
  var resetNote = window.sessionStorage.getItem("outlier-reset");
  if (resetNote) {
    window.sessionStorage.removeItem("outlier-reset");
    setTimeout(function () { toast(resetNote); }, 240);
  }

  /* ------------------------------------------------------------ sources */

  document.addEventListener("click", function (event) {
    var renameBtn = event.target.closest(".rename-source");
    if (renameBtn) {
      var id = renameBtn.dataset.sourceId;
      var label = document.querySelector('.src-name[data-source-id="' + id + '"]');
      var current = label ? label.textContent.trim() : "";
      var next = window.prompt("Rename this source:", current);
      if (next === null) return;
      next = next.trim();
      if (!next) { toast("Name cannot be empty", true); return; }

      post("/api/source/" + id, { name: next }, "PATCH")
        .then(function (data) {
          if (!data.ok) throw new Error(data.error || "Rename failed");
          if (label) label.textContent = data.name;
          toast("Renamed");
        })
        .catch(function (error) { toast(error.message, true); });
      return;
    }

    var deleteBtn = event.target.closest(".delete-source");
    if (deleteBtn) {
      var sourceId = deleteBtn.dataset.sourceId;
      var name = deleteBtn.dataset.sourceName || "this source";
      if (!window.confirm('Delete "' + name + '" and every post captured from it?\n\nThis cannot be undone.')) return;

      post("/api/source/" + sourceId, undefined, "DELETE")
        .then(function (data) {
          if (!data.ok) throw new Error(data.error || "Delete failed");
          // The grid renders each source as a card, not a table row, so remove
          // the whole card — closest("tr") always missed and left it on screen.
          var card = deleteBtn.closest(".source-card") || deleteBtn.closest("tr");
          if (card) {
            card.style.transition = "opacity 0.25s, transform 0.25s";
            card.style.opacity = "0";
            card.style.transform = "translateX(-14px)";
            setTimeout(function () { card.remove(); }, 260);
          }
          toast("Deleted " + data.deleted + " posts");
        })
        .catch(function (err) {
          var msg = (err && err.message) || "Could not delete that source";
          // A stale page carries an old CSRF token; the cure is a reload, so
          // say that instead of a dead-end error.
          if (/csrf|token/i.test(msg)) {
            msg = "Your session refreshed in another tab — reload this page and try again.";
          }
          toast(msg, true);
        });
    }
  });

  /* ----------------------------------------------------- source kind */

  // Profile vs Page can't always be told apart automatically, so the label is
  // editable on the source card. The choice is saved straight away and sticks —
  // a later scan won't overwrite it (see upsert_source).
  document.addEventListener("change", function (event) {
    var select = event.target.closest(".kind-select");
    if (!select) return;
    var id = select.dataset.sourceId;
    select.disabled = true;
    post("/api/source/" + id, { kind: select.value }, "PATCH")
      .then(function (data) {
        if (!data.ok) throw new Error(data.error || "Could not update");
        toast("Marked as " + select.value);
      })
      .catch(function (err) {
        toast((err && err.message) || "Could not update the type", true);
      })
      .then(function () { select.disabled = false; });
  });

  /* ------------------------------------------------------------ save */

  document.addEventListener("click", function (event) {
    var btn = event.target.closest(".save-btn");
    if (!btn) return;
    event.preventDefault();

    post("/api/save/" + btn.dataset.postId)
      .then(function (data) {
        if (!data.ok) throw new Error("save failed");
        btn.classList.toggle("is-saved", data.saved);
        toast(data.saved ? "Saved to library" : "Removed from library");
      })
      .catch(function () { toast("Could not save that post", true); });
  });

  /* ------------------------------------------------------------ copy */

  document.addEventListener("click", function (event) {
    var btn = event.target.closest(".copy-btn");
    if (!btn) return;

    var target = document.getElementById(btn.dataset.copyTarget);
    if (!target) return;

    navigator.clipboard.writeText(target.textContent.trim())
      .then(function () { toast("Copied to clipboard"); })
      .catch(function () { toast("Clipboard blocked by the browser", true); });
  });

  /* ------------------------------------------------------------ demo data */

  function demoRequest(method, label) {
    return function () {
      toast(label + "…");
      post("/api/demo", undefined, method)
        .then(function () { window.location.reload(); })
        .catch(function () { toast("That didn't work", true); });
    };
  }

  var loadDemo = document.getElementById("load-demo");
  if (loadDemo) loadDemo.addEventListener("click", demoRequest("POST", "Loading sample data"));

  var clearDemo = document.getElementById("clear-demo");
  if (clearDemo) clearDemo.addEventListener("click", demoRequest("DELETE", "Clearing sample data"));

  /* ------------------------------------------------------------ graphics */

  /* One handler for every "Generate graphic" button on the page.
   *
   * This used to be built per variant, in a closure, at the moment JavaScript
   * rendered a fresh remix — so a variant loaded from the database had no
   * button at all, and leaving the page and coming back lost the option. Both
   * paths now render the same markup with the hook and body as data
   * attributes, and this reads them off whichever button was pressed.
   */
  document.addEventListener("click", function (event) {
    if (!event.target.closest) return;
    var button = event.target.closest(".graphic-btn");
    if (!button) return;

    var block = button.closest(".variant");
    if (!block) return;

    // Built on first press and kept afterwards, so a regenerate is a tweak of
    // what was typed rather than a retype.
    var direction = block.querySelector(".graphic-direction");
    if (!direction) {
      direction = document.createElement("div");
      direction.className = "graphic-direction";

      var brief = document.createElement("textarea");
      brief.className = "graphic-brief";
      brief.rows = 2;
      brief.placeholder =
        "Optional: describe the image you want — subject, style, colours, mood.";

      /* Put the words on the picture.
       *
       * The default is no text at all, because image models render lettering
       * badly often enough that it has to be opt-in. But it is a thing people
       * plainly want, and making them discover it by typing the word "text"
       * into a free-form brief is a trick, not a feature.
       *
       * Prefilled with the variant's opening line rather than the whole post:
       * a headline sets cleanly, a paragraph comes back as soup. Editable,
       * because the best line for a graphic is often shorter than the hook.
       */
      var wordsRow = document.createElement("label");
      wordsRow.className = "graphic-words";
      var wordsOn = document.createElement("input");
      wordsOn.type = "checkbox";
      wordsOn.className = "graphic-words-on";
      var wordsLabel = document.createElement("span");
      wordsLabel.textContent = "Put the words on the image";
      wordsRow.appendChild(wordsOn);
      wordsRow.appendChild(wordsLabel);

      var wordsText = document.createElement("input");
      wordsText.type = "text";
      wordsText.className = "graphic-words-text";
      wordsText.maxLength = 120;
      wordsText.hidden = true;
      wordsText.placeholder = "The line to set into the picture";
      wordsText.value = (button.dataset.hook || "").slice(0, 120);

      var wordsNote = document.createElement("p");
      wordsNote.className = "fine graphic-words-note";
      wordsNote.hidden = true;
      wordsNote.textContent =
        "The picture is made with clear space for it. You can drag the words, "
        + "resize and recolour them after it appears.";

      wordsOn.addEventListener("change", function () {
        wordsText.hidden = !wordsOn.checked;
        wordsNote.hidden = !wordsOn.checked;
        if (wordsOn.checked) wordsText.focus();
      });

      var go = document.createElement("button");
      go.type = "button";
      go.className = "btn btn-ghost graphic-go";
      go.textContent = "Generate";

      direction.appendChild(brief);
      direction.appendChild(wordsRow);
      direction.appendChild(wordsText);
      direction.appendChild(wordsNote);
      direction.appendChild(go);
      block.appendChild(direction);

      go.addEventListener("click", function () { runGraphic(button, block); });
      brief.addEventListener("keydown", function (e) {
        if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) runGraphic(button, block);
      });
      brief.focus();
      return;                       // first press opens the brief, spends nothing
    }
    runGraphic(button, block);
  });

  /* ------------------------------------------------- caption over image */

  /* Real type, laid over the picture rather than painted into it.
   *
   * The image model used to set the lettering, which meant it was frequently
   * misspelled, always a gamble, and — being pixels — impossible to move,
   * resize or recolour afterwards. The picture is now generated as a clean
   * plate with quiet space through the middle, and the words go on top here.
   *
   * Position is kept as a FRACTION of the image, never pixels: the editor
   * shows the picture at whatever width the column allows, while the export
   * draws it at its native 1024. Storing pixels would put the headline
   * somewhere else in the saved file than it sat on screen.
   */
  var CAPTION_FONTS = [
    { label: "Display", stack: "'Fraunces', Georgia, serif" },
    { label: "Sans", stack: "'Inter', system-ui, sans-serif" },
    { label: "Mono", stack: "ui-monospace, SFMono-Regular, Menlo, monospace" }
  ];
  var CAPTION_COLOURS = ["#ffffff", "#050b07", "#6ee7b7", "#d9b45f", "#e07a5f"];

  function buildCaptionEditor(wrap, img, text) {
    var state = {
      text: text,
      x: 0.5,            // dead centre to begin with
      y: 0.5,
      size: 0.075,       // fraction of image height, so it survives export
      font: CAPTION_FONTS[0].stack,
      colour: "#ffffff",
      shadow: true
    };

    var stage = document.createElement("div");
    stage.className = "cap-stage";
    stage.appendChild(img);

    /* Centre guides. Shown only while the headline is actually snapped, so
       they read as confirmation rather than decoration. */
    var guideX = document.createElement("div");
    guideX.className = "cap-guide cap-guide-x";
    var guideY = document.createElement("div");
    guideY.className = "cap-guide cap-guide-y";
    stage.appendChild(guideX);
    stage.appendChild(guideY);

    var layer = document.createElement("div");
    layer.className = "cap-layer";
    layer.title = "Drag to move · double-click to centre";
    stage.appendChild(layer);
    wrap.appendChild(stage);

    function paint() {
      layer.style.left = (state.x * 100) + "%";
      layer.style.top = (state.y * 100) + "%";
      layer.style.fontSize = (state.size * (stage.clientHeight || 512)) + "px";
      layer.style.fontFamily = state.font;
      layer.style.color = state.colour;
      layer.style.textShadow = state.shadow
        ? "0 2px 18px rgba(0,0,0,0.55), 0 1px 3px rgba(0,0,0,0.45)"
        : "none";
      layer.textContent = state.text;
    }

    /* Pointer events rather than mouse events, so a finger behaves like a
       cursor and the drag survives leaving the element. */
    var dragging = false;
    layer.addEventListener("pointerdown", function (event) {
      dragging = true;
      layer.setPointerCapture(event.pointerId);
      layer.classList.add("is-dragging");
      event.preventDefault();
    });
    /* Sticky centre.
     *
     * Dead centre is the position people actually want most of the time, and
     * hitting 0.500 by hand on a dragged element is luck. Within SNAP_PX of
     * the middle the headline locks to exactly 0.5 and a guide appears; drag
     * further and it releases. Measured in PIXELS, not in fractions of the
     * image, so the pull feels identical whatever size the picture is
     * displayed at — a fraction would snap hard on a small preview and
     * barely at all on a large one.
     */
    var SNAP_PX = 11;

    layer.addEventListener("pointermove", function (event) {
      if (!dragging) return;
      var box = stage.getBoundingClientRect();
      var x = (event.clientX - box.left) / box.width;
      var y = (event.clientY - box.top) / box.height;

      var snapX = Math.abs(x - 0.5) * box.width <= SNAP_PX;
      var snapY = Math.abs(y - 0.5) * box.height <= SNAP_PX;
      if (snapX) x = 0.5;
      if (snapY) y = 0.5;

      // Clamped, so the headline cannot be dragged off its own picture.
      state.x = Math.max(0.04, Math.min(x, 0.96));
      state.y = Math.max(0.06, Math.min(y, 0.94));

      guideX.classList.toggle("is-on", snapX);
      guideY.classList.toggle("is-on", snapY);
      layer.classList.toggle("is-snapped", snapX || snapY);
      paint();
    });
    ["pointerup", "pointercancel"].forEach(function (name) {
      layer.addEventListener(name, function () {
        dragging = false;
        layer.classList.remove("is-dragging");
        // The guides said "you are snapped"; the drag is over, so they stop.
        guideX.classList.remove("is-on");
        guideY.classList.remove("is-on");
      });
    });

    // The way back to dead centre that needs no aim at all.
    layer.addEventListener("dblclick", function () {
      state.x = 0.5;
      state.y = 0.5;
      paint();
      layer.classList.add("is-snapped");
      guideX.classList.add("is-on");
      guideY.classList.add("is-on");
      window.setTimeout(function () {
        guideX.classList.remove("is-on");
        guideY.classList.remove("is-on");
      }, 420);
    });

    var controls = document.createElement("div");
    controls.className = "cap-controls";

    var edit = document.createElement("input");
    edit.type = "text";
    edit.className = "cap-text";
    edit.value = state.text;
    edit.maxLength = 120;
    edit.setAttribute("aria-label", "Headline text");
    edit.addEventListener("input", function () {
      state.text = edit.value;
      paint();
    });
    controls.appendChild(edit);

    var row = document.createElement("div");
    row.className = "cap-row";

    var size = document.createElement("input");
    size.type = "range";
    size.min = "3";
    size.max = "16";
    size.step = "0.5";
    size.value = String(state.size * 100);
    size.className = "cap-size";
    size.setAttribute("aria-label", "Text size");
    size.addEventListener("input", function () {
      state.size = parseFloat(size.value) / 100;
      paint();
    });
    row.appendChild(size);

    var font = document.createElement("select");
    font.className = "cap-font";
    font.setAttribute("aria-label", "Typeface");
    CAPTION_FONTS.forEach(function (option) {
      var el = document.createElement("option");
      el.value = option.stack;
      el.textContent = option.label;
      font.appendChild(el);
    });
    font.addEventListener("change", function () {
      state.font = font.value;
      paint();
    });
    row.appendChild(font);

    var swatches = document.createElement("div");
    swatches.className = "cap-swatches";
    CAPTION_COLOURS.forEach(function (colour) {
      var dot = document.createElement("button");
      dot.type = "button";
      dot.className = "cap-swatch" + (colour === state.colour ? " selected" : "");
      dot.style.background = colour;
      dot.title = colour;
      dot.setAttribute("aria-label", "Text colour " + colour);
      dot.addEventListener("click", function () {
        state.colour = colour;
        swatches.querySelectorAll(".cap-swatch").forEach(function (other) {
          other.classList.toggle("selected", other === dot);
        });
        paint();
      });
      swatches.appendChild(dot);
    });
    row.appendChild(swatches);

    var shadow = document.createElement("label");
    shadow.className = "cap-shadow";
    var shadowOn = document.createElement("input");
    shadowOn.type = "checkbox";
    shadowOn.checked = state.shadow;
    shadowOn.addEventListener("change", function () {
      state.shadow = shadowOn.checked;
      paint();
    });
    shadow.appendChild(shadowOn);
    shadow.appendChild(document.createTextNode("Shadow"));
    row.appendChild(shadow);

    controls.appendChild(row);

    // Composites on the way out. A plain link would save the bare plate.
    var save = document.createElement("button");
    save.type = "button";
    save.className = "btn btn-ghost graphic-dl";
    save.textContent = "Download";
    save.addEventListener("click", function () {
      exportCaptioned(img, state, save);
    });
    controls.appendChild(save);

    var hint = document.createElement("p");
    hint.className = "fine cap-hint";
    hint.textContent =
      "Drag the words to move them — they snap to the centre. "
      + "Double-click to put them back.";
    controls.appendChild(hint);

    wrap.appendChild(controls);

    // Sized against the rendered image, so this waits for layout.
    requestAnimationFrame(paint);
    window.addEventListener("resize", paint);
  }

  /* Composite at the image's own resolution rather than the size it happens to
     be displayed at, so the saved file is the full 1024 and not a screenshot
     of a column. */
  function exportCaptioned(img, state, button) {
    var label = button.textContent;
    button.disabled = true;
    button.textContent = "Saving…";

    // The face has to be loaded, or canvas quietly falls back to a default and
    // the saved file does not match what is on screen.
    var ready = (document.fonts && document.fonts.ready)
      ? document.fonts.ready : Promise.resolve();

    ready.then(function () {
      var w = img.naturalWidth || 1024;
      var h = img.naturalHeight || 1024;
      var canvas = document.createElement("canvas");
      canvas.width = w;
      canvas.height = h;
      var ctx = canvas.getContext("2d");
      ctx.drawImage(img, 0, 0, w, h);

      var fontSize = state.size * h;
      ctx.font = "600 " + fontSize + "px " + state.font;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillStyle = state.colour;

      // Wrapped by measurement: canvas has no line breaking of its own, so a
      // long headline would run off both edges.
      var maxWidth = w * 0.84;
      var words = String(state.text).split(/\s+/).filter(Boolean);
      var lines = [];
      var line = "";
      words.forEach(function (word) {
        var candidate = line ? line + " " + word : word;
        if (ctx.measureText(candidate).width > maxWidth && line) {
          lines.push(line);
          line = word;
        } else {
          line = candidate;
        }
      });
      if (line) lines.push(line);

      var lineHeight = fontSize * 1.18;
      var startY = (state.y * h) - ((lines.length - 1) * lineHeight) / 2;

      if (state.shadow) {
        ctx.shadowColor = "rgba(0,0,0,0.55)";
        ctx.shadowBlur = fontSize * 0.35;
        ctx.shadowOffsetY = fontSize * 0.04;
      }
      lines.forEach(function (text, index) {
        ctx.fillText(text, state.x * w, startY + index * lineHeight);
      });

      var url;
      try {
        url = canvas.toDataURL("image/png");
      } catch (error) {
        // Only reachable if the plate came from another origin, which the
        // server inlines specifically to prevent.
        toast("Could not save — the image came from another site", true);
        button.disabled = false;
        button.textContent = label;
        return;
      }

      var link = document.createElement("a");
      link.href = url;
      link.download = "tallgrass-graphic.png";
      document.body.appendChild(link);
      link.click();
      link.remove();
      button.disabled = false;
      button.textContent = label;
      toast("Saved");
    });
  }

  function runGraphic(button, block) {
    var brief = block.querySelector(".graphic-brief");
    var go = block.querySelector(".graphic-go");
    var label = button.textContent;
    button.disabled = true;
    if (go) go.disabled = true;
    button.textContent = "Generating…";

    // The space the picture will occupy, claimed immediately and shimmering
    // while it is empty. A button label is too small and too far from where
    // the eye is to read as anything happening.
    var old = block.querySelector(".variant-graphic");
    if (old) old.remove();

    var wrap = document.createElement("div");
    wrap.className = "variant-graphic is-loading";
    var skeleton = document.createElement("div");
    skeleton.className = "graphic-skeleton";
    var note = document.createElement("div");
    note.className = "graphic-progress";
    note.textContent = "Painting your graphic…";
    wrap.appendChild(skeleton);
    wrap.appendChild(note);
    block.appendChild(wrap);

    var started = Date.now();
    var ticker = window.setInterval(function () {
      var seconds = Math.round((Date.now() - started) / 1000);
      note.textContent = "Painting your graphic… " + seconds + "s" +
        (seconds >= 30 ? " — larger images can take a minute" : "");
    }, 1000);
    function stop() { window.clearInterval(ticker); }

    post("/api/graphic", {
      hook: button.dataset.hook || "",
      // Set only by the "another like the original" button. The server turns
      // it into a brief from what was actually captured about that post's
      // graphic, and refuses if nothing was.
      like_post_id: button.dataset.likePostId
        ? parseInt(button.dataset.likePostId, 10) : null,
      // Only when the box is ticked. Empty means the no-text default holds.
      caption_text: (function () {
        var on = block.querySelector(".graphic-words-on");
        var text = block.querySelector(".graphic-words-text");
        return (on && on.checked && text) ? text.value.trim() : "";
      })(),
      // The body as well as the hook. A hook is a fragment written to intrigue
      // and describes no scene, which is why the pictures had nothing to do
      // with the post they illustrated.
      body: button.dataset.body || "",
      instructions: brief ? brief.value.trim() : ""
    })
      .then(function (data) {
        if (!data.ok) throw new Error(data.error || "Could not generate a graphic");
        stop();
        var img = document.createElement("img");
        img.alt = "Generated graphic";
        var dl = document.createElement("a");
        dl.href = data.image;
        dl.download = "tallgrass-graphic.png";
        dl.className = "graphic-dl";
        dl.textContent = "Download";

        var caption = (function () {
          var on = block.querySelector(".graphic-words-on");
          var text = block.querySelector(".graphic-words-text");
          return (on && on.checked && text) ? text.value.trim() : "";
        })();

        // Held until the bytes decode. Swapping on the response alone leaves a
        // blank frame where the shimmer was.
        img.addEventListener("load", function () {
          wrap.className = "variant-graphic";
          wrap.textContent = "";
          wrap.appendChild(img);
          if (caption) {
            // Real type over the picture, not pixels painted into it. The
            // editor makes its own Download, because saving has to composite
            // the words onto the plate — the plain link would save the plate.
            buildCaptionEditor(wrap, img, caption);
          } else {
            wrap.appendChild(dl);
          }
        });
        img.addEventListener("error", function () {
          wrap.remove();
          toast("The image could not be displayed", true);
        });
        img.src = data.image;
        button.textContent = "Regenerate graphic";
      })
      .catch(function (error) {
        stop();
        wrap.remove();
        toast(error.message, true);
        button.textContent = label;
      })
      .finally(function () {
        stop();
        button.disabled = false;
        if (go) go.disabled = false;
      });
  }

  /* ------------------------------------------------------ delete a post */

  // Delegated from the document, because post cards appear on the feed, on a
  // group page and in the library, and every one of them carries this button.
  document.addEventListener("click", function (event) {
    var button = event.target.closest && event.target.closest(".delete-post");
    if (!button) return;

    var card = button.closest("[data-post-id]");
    if (!window.confirm("Delete this post?\n\nIt is removed from your dashboard " +
                        "and stops counting toward the group's baseline. " +
                        "Re-scanning the group will capture it again.")) return;

    button.disabled = true;
    post("/api/post/" + button.dataset.postId, undefined, "DELETE")
      .then(function (data) {
        if (!data.ok) throw new Error(data.error || "Could not delete that post");
        // Faded out rather than removed outright, so the row does not vanish
        // from under the cursor with no sign of what happened.
        if (card) {
          card.style.transition = "opacity 0.25s var(--ease), transform 0.25s var(--ease)";
          card.style.opacity = "0";
          card.style.transform = "scale(0.98)";
          window.setTimeout(function () { card.remove(); }, 260);
        }
        toast("Post deleted.");
      })
      .catch(function (error) {
        toast(error.message, true);
        button.disabled = false;
      });
  });

  /* --------------------------------------------------------- feedback */

  var fbSubmit = document.getElementById("fb-submit");
  if (fbSubmit) {
    fbSubmit.addEventListener("click", function () {
      var title = document.getElementById("fb-title");
      var body = document.getElementById("fb-body");
      var kindEl = document.querySelector('input[name="fb-kind"]:checked');
      if (!title.value.trim()) {
        toast("Give it a one-line summary first.", true);
        title.focus();
        return;
      }
      fbSubmit.disabled = true;
      post("/api/feedback", {
        kind: kindEl ? kindEl.value : "idea",
        title: title.value.trim(),
        body: body.value.trim()
      })
        .then(function (data) {
          if (!data.ok) throw new Error(data.error || "Could not send that");
          // Reloaded rather than prepended: the board is sorted, and guessing
          // where a new row belongs is how a list starts lying about its order.
          window.sessionStorage.setItem("outlier-reset", "Thanks — that's been sent.");
          window.location.href = "/feedback?sort=new";
        })
        .catch(function (error) {
          toast(error.message, true);
          fbSubmit.disabled = false;
        });
    });
  }

  // One delegated listener for the whole board, so rows cost nothing to add.
  var fbList = document.querySelector(".fb-list");
  if (fbList) {
    fbList.addEventListener("click", function (event) {
      var vote = event.target.closest(".fb-vote");
      if (vote) {
        vote.disabled = true;
        post("/api/feedback/" + vote.dataset.id + "/vote", {})
          .then(function (data) {
            if (!data.ok) return;
            vote.classList.toggle("is-voted", !!data.voted);
            vote.querySelector(".fb-vote-n").textContent = data.votes;
          })
          .catch(function () { toast("Could not register that vote", true); })
          .finally(function () { vote.disabled = false; });
        return;
      }

      var set = event.target.closest(".fb-set");
      if (set) {
        var note = null;
        // Only asked for on the outcomes where silence would be rude.
        if (set.dataset.status === "declined" || set.dataset.status === "shipped") {
          note = window.prompt(
            "Optional note to everyone who voted for this:", "");
          if (note === null) return;
        }
        set.disabled = true;
        post("/api/feedback/" + set.dataset.id + "/status",
             { status: set.dataset.status, note: note || undefined })
          .then(function (data) {
            if (!data.ok) throw new Error(data.error || "Could not update");
            toast("Marked " + data.status + " — " + data.notified +
                  " notified.");
            window.location.reload();
          })
          .catch(function (error) {
            toast(error.message, true);
            set.disabled = false;
          });
      }
    });
  }

  /* ----------------------------------------------------- notifications */

  var notif = document.getElementById("notif");
  if (notif) {
    var bell = document.getElementById("notif-bell");
    var dot = document.getElementById("notif-dot");
    var panel = document.getElementById("notif-panel");
    var list = document.getElementById("notif-list");
    var clearBtn = document.getElementById("notif-clear");
    var loaded = false;

    function renderNotifications(data) {
      list.textContent = "";
      var items = (data && data.items) || [];
      if (!items.length) {
        var empty = document.createElement("p");
        empty.className = "notif-empty";
        empty.textContent = "Nothing yet.";
        list.appendChild(empty);
        return;
      }
      items.forEach(function (item) {
        // A link when there is somewhere to go, a plain block when there is
        // not — an anchor to nowhere is a promise the panel cannot keep.
        var row = document.createElement(item.url ? "a" : "div");
        row.className = "notif-item" + (item.read_at ? "" : " is-unread");
        if (item.url) row.href = item.url;

        var title = document.createElement("span");
        title.className = "notif-title";
        title.textContent = item.title || "";
        row.appendChild(title);

        if (item.body) {
          var body = document.createElement("span");
          body.className = "notif-body";
          body.textContent = item.body;
          row.appendChild(body);
        }
        var when = document.createElement("span");
        when.className = "notif-when";
        when.textContent = (item.created_at || "").slice(0, 16);
        row.appendChild(when);

        list.appendChild(row);
      });
    }

    function setUnread(n) {
      dot.hidden = !n;
      dot.textContent = n > 9 ? "9+" : String(n || "");
    }

    function loadNotifications() {
      return fetch("/api/notifications", { headers: { "X-CSRF-Token": CSRF } })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (!data || !data.ok) return;
          setUnread(data.unread);
          renderNotifications(data);
          loaded = true;
        })
        .catch(function () { /* a badge is not worth an error */ });
    }

    bell.addEventListener("click", function (event) {
      event.stopPropagation();
      var opening = panel.hidden;
      panel.hidden = !opening;
      if (!opening) return;

      if (!loaded) loadNotifications();
      // Opening the panel is reading them. The badge clears on open rather
      // than making anyone hunt for a button to say they have looked. The
      // rows keep their own unread styling for this view, so what is new is
      // still visible after the count goes.
      if (!dot.hidden) {
        post("/api/notifications/read", {})
          .then(function (data) { setUnread(data && data.unread); })
          .catch(function () {});
      }
    });

    clearBtn.addEventListener("click", function (event) {
      event.stopPropagation();
      post("/api/notifications/read", {})
        .then(function () { return loadNotifications(); })
        .catch(function () {});
    });

    document.addEventListener("click", function (event) {
      if (!panel.hidden && !notif.contains(event.target)) panel.hidden = true;
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") panel.hidden = true;
    });

    // The badge only. The list itself waits until the panel is opened.
    fetch("/api/notifications", { headers: { "X-CSRF-Token": CSRF } })
      .then(function (r) { return r.json(); })
      .then(function (data) { if (data && data.ok) setUnread(data.unread); })
      .catch(function () {});
  }

  var saveUsername = document.getElementById("save-username");
  if (saveUsername) {
    var usernameField = document.getElementById("username-field");
    function saveName() {
      var value = usernameField.value.trim();
      if (!value) { usernameField.focus(); return; }
      saveUsername.disabled = true;
      post("/api/username", { username: value })
        .then(function (data) {
          // The server owns the rules — taken, reserved, wrong shape — so the
          // message shown is the server's, not a guess made here.
          if (!data.ok) throw new Error(data.error || "Could not set that name");
          toast("You're " + data.username + " now.");
        })
        .catch(function (error) {
          toast(error.message, true);
          usernameField.focus();
        })
        .finally(function () { saveUsername.disabled = false; });
    }
    saveUsername.addEventListener("click", saveName);
    usernameField.addEventListener("keydown", function (event) {
      if (event.key === "Enter") saveName();
    });
  }



  var resetAll = document.getElementById("reset-all");
  if (resetAll) {
    resetAll.addEventListener("click", function () {
      // Destructive and unrecoverable — confirm before firing.
      if (!window.confirm("Delete every captured post, group, and saved item?\n\nThis cannot be undone.")) return;
      toast("Deleting everything…");
      post("/api/reset")
        .then(function (data) {
          // Say what actually went, so a reset that quietly did nothing is
          // distinguishable from one that worked.
          var posts = (data && data.posts) || 0;
          var groups = (data && data.sources) || 0;
          window.sessionStorage.setItem("outlier-reset",
            "Deleted " + posts + " post" + (posts === 1 ? "" : "s") +
            " across " + groups + " group" + (groups === 1 ? "" : "s") + ".");
          window.location.href = "/";
        })
        .catch(function () { toast("Reset failed", true); });
    });
  }

  /* ------------------------------------------------------------ install */

  var openFolder = document.getElementById("open-folder");
  if (openFolder) {
    var folderMsg = document.getElementById("open-folder-msg");

    openFolder.addEventListener("click", function () {
      folderMsg.className = "istep-msg";
      folderMsg.textContent = "Opening…";

      post("/api/open-folder")
        .then(function (data) {
          if (!data.ok) throw new Error(data.error || "Could not open the folder");
          folderMsg.className = "istep-msg ok";
          folderMsg.textContent = "Opened. Look for a window showing the 'extension' folder.";
        })
        .catch(function (error) {
          // Falling back to the copyable path keeps the step doable.
          folderMsg.className = "istep-msg error";
          folderMsg.textContent = error.message + " — copy the path below instead.";
        });
    });
  }

  /* ------------------------------------------------------------ Sage */

  var chatForm = document.getElementById("chat-form");
  if (chatForm) {
    var chat = document.getElementById("chat");
    var chatInput = document.getElementById("chat-input");
    var chatSend = document.getElementById("chat-send");
    var chatStatus = document.getElementById("chat-status");
    var suggested = document.getElementById("suggested");

    function addMessage(role, text) {
      var empty = document.getElementById("chat-empty");
      if (empty) empty.remove();

      var wrap = document.createElement("div");
      wrap.className = "msg msg-" + role;

      if (role === "assistant") {
        var who = document.createElement("span");
        who.className = "msg-who";
        who.textContent = "Sage";
        wrap.appendChild(who);
      }

      var body = document.createElement("div");
      body.className = "msg-body";
      // textContent — model output is never trusted as markup.
      body.textContent = text;
      wrap.appendChild(body);

      chat.appendChild(wrap);
      chat.scrollTop = chat.scrollHeight;
      return wrap;
    }

    function thinkingBubble() {
      var wrap = document.createElement("div");
      wrap.className = "msg msg-assistant";
      var dots = document.createElement("div");
      dots.className = "thinking";
      dots.innerHTML = "<span></span><span></span><span></span>";
      wrap.appendChild(dots);
      chat.appendChild(wrap);
      chat.scrollTop = chat.scrollHeight;
      return wrap;
    }

    var chatStop = document.getElementById("chat-stop");
    var sageAbort = null;

    function setAsking(asking) {
      chatInput.disabled = asking;
      chatSend.disabled = asking;
      if (chatStop) chatStop.hidden = !asking;
    }

    function askSage(question) {
      if (!question) return;

      addMessage("user", question);
      chatInput.value = "";
      setAsking(true);
      if (suggested) suggested.style.display = "none";
      chatStatus.className = "chat-status";
      chatStatus.textContent = "";

      var pending = thinkingBubble();
      var body = null;
      var failure = null;

      // The dots stay until the first real word, then the bubble becomes the
      // answer and fills in place.
      function ensureBody() {
        if (body) return;
        pending.innerHTML = "";
        var who = document.createElement("span");
        who.className = "msg-who";
        who.textContent = "Sage";
        pending.appendChild(who);
        body = document.createElement("div");
        body.className = "msg-body is-streaming";
        pending.appendChild(body);
      }

      sageAbort = new AbortController();

      fetch("/api/sage/stream", {
        method: "POST",
        headers: { "X-CSRF-Token": CSRF, "Content-Type": "application/json" },
        body: JSON.stringify({ message: question }),
        signal: sageAbort.signal
      })
        .then(function (response) {
          if (response.status === 401) {
            window.location.href = "/login";
            throw new Error("Signed out");
          }
          if (!response.ok || !response.body) {
            throw new Error("Server error (" + response.status + ")");
          }
          return readEvents(response.body.getReader(), function (event) {
            if (event.type === "delta") {
              ensureBody();
              // textContent — model output is never trusted as markup.
              body.textContent += event.text;
              chat.scrollTop = chat.scrollHeight;
            } else if (event.type === "error") {
              failure = event.error;
            }
          });
        })
        .then(function () {
          if (failure) throw new Error(failure);
          if (!body) throw new Error("Sage returned an empty response");
        })
        .catch(function (error) {
          // A cancel is the user getting what they asked for, not a failure.
          // Whatever already arrived stays on screen and stays in the history.
          if (error.name === "AbortError") {
            chatStatus.className = "chat-status";
            chatStatus.textContent = "Stopped.";
            return;
          }
          if (!body) pending.remove();
          chatStatus.className = "chat-status error";
          chatStatus.textContent = error.message;
        })
        .finally(function () {
          if (body) body.classList.remove("is-streaming");
          sageAbort = null;
          setAsking(false);
          chatInput.focus();
        });
    }

    if (chatStop) {
      chatStop.addEventListener("click", function () {
        if (sageAbort) sageAbort.abort();
      });
    }

    chatForm.addEventListener("submit", function (event) {
      event.preventDefault();
      askSage(chatInput.value.trim());
    });

    if (suggested) {
      suggested.addEventListener("click", function (event) {
        var chip = event.target.closest(".chip-btn");
        if (chip) askSage(chip.dataset.prompt);
      });
    }

    var clearChat = document.getElementById("clear-chat");
    if (clearChat) {
      clearChat.addEventListener("click", function () {
        if (!window.confirm("Clear this conversation?")) return;
        post("/api/sage/clear").then(function () { window.location.reload(); });
      });
    }
  }

  /* ------------------------------------------------------------ AI config */

  var saveAi = document.getElementById("save-ai");
  if (saveAi) {
    var aiMsg = document.getElementById("ai-msg");

    document.querySelectorAll('input[name="provider"]').forEach(function (radio) {
      radio.addEventListener("change", function () {
        document.querySelectorAll(".provider").forEach(function (label) {
          label.classList.toggle("selected", label.contains(radio) && radio.checked);
        });
        // Swap the model placeholder to the chosen provider's default.
        var model = document.getElementById("ai-model");
        if (model) {
          model.value = radio.value === "anthropic" ? "claude-opus-5" : "gpt-4o";
        }
      });
    });

    saveAi.addEventListener("click", function () {
      var provider = document.querySelector('input[name="provider"]:checked');
      var key = document.getElementById("ai-key").value.trim();
      var model = document.getElementById("ai-model").value.trim();

      if (!provider) {
        aiMsg.className = "msg-line error";
        aiMsg.textContent = "Pick a provider.";
        return;
      }

      aiMsg.className = "msg-line";
      aiMsg.textContent = "Saving…";

      post("/api/sage/config", { provider: provider.value, key: key, model: model })
        .then(function (data) {
          if (!data.ok) throw new Error(data.error || "Save failed");
          aiMsg.className = "msg-line ok";
          aiMsg.textContent = data.has_key
            ? "Saved. Sage is ready — open the Sage tab."
            : "Provider saved, but no key is set yet.";
          document.getElementById("ai-key").value = "";
        })
        .catch(function (error) {
          aiMsg.className = "msg-line error";
          aiMsg.textContent = error.message;
        });
    });
  }

  /* --------------------------------------------------------- brand profile */

  var saveBrand = document.getElementById("save-brand");
  if (saveBrand) {
    var brandMsg = document.getElementById("brand-msg");
    saveBrand.addEventListener("click", function () {
      function val(id) {
        var el = document.getElementById(id);
        return el ? el.value.trim() : "";
      }
      var payload = {
        name: val("brand-name"), offer: val("brand-offer"),
        audience: val("brand-audience"), voice: val("brand-voice"),
        visual: val("brand-visual"), colors: val("brand-colors"),
      };
      brandMsg.className = "msg-line";
      brandMsg.textContent = "Saving…";
      post("/api/brand", payload)
        .then(function (data) {
          if (!data.ok) throw new Error(data.error || "Save failed");
          brandMsg.className = "msg-line ok";
          brandMsg.textContent = "Saved. Sage and your graphics will use this now.";
        })
        .catch(function (error) {
          brandMsg.className = "msg-line error";
          brandMsg.textContent = error.message;
        });
    });
  }


  /* ------------------------------------------------------------ account */

  /* ------------------------------------------------ connect the extension */

  // Typing a dashboard URL and pasting a key is friction that solves nothing:
  // this page knows both. A content script running on this origin takes them
  // directly, so there is nothing to type and — when the extension isn't
  // already wired here — nothing to click either.
  //
  // This runs on every dashboard page, not just Capture and Account. Landing
  // anywhere while signed in is enough to connect; the visible copy below is
  // just reporting, and is skipped on pages that have no connect block.
  {
    var connectBtn = document.getElementById("connect-btn");
    var connectCopy = document.getElementById("connect-copy");
    var connectMsg = document.getElementById("connect-msg");
    var extensionSeen = false;

    function say(el, text, cls) {
      if (!el) return;
      el.textContent = text;
      if (cls !== undefined) el.className = cls;
    }

    function issueKey(silent) {
      if (connectBtn) connectBtn.disabled = true;
      say(connectMsg, silent ? "Connecting…" : "Issuing a key…", "msg-line");

      return post("/api/account/connect")
        .then(function (data) {
          if (!data.ok) throw new Error(data.error || "Could not issue a key");
          // Handed to the content script, which writes it into extension
          // storage. The key never touches the address bar or the clipboard.
          window.dispatchEvent(new CustomEvent("outlier:connect", {
            detail: { apiKey: data.api_key }
          }));
        })
        .catch(function (error) {
          if (connectBtn) connectBtn.disabled = false;
          say(connectMsg, error.message, "msg-line error");
        });
    }

    window.addEventListener("outlier:extension-present", function (event) {
      extensionSeen = true;
      var detail = event.detail || {};
      var version = detail.version ? " (v" + detail.version + ")" : "";
      if (connectBtn) {
        connectBtn.style.display = "";
        connectBtn.textContent = "Reconnect";
      }

      if (detail.connected) {
        say(connectCopy, "Extension connected" + version +
                         ". Captures come straight here.");
        return;
      }

      // Nothing to click. The page is signed in and knows its own address, so
      // asking the user to confirm that adds a step and no information. A key
      // is only minted when the extension is unconnected or pointed somewhere
      // else, so this cannot rotate the key on every page load.
      say(connectCopy, "Extension detected" + version + ". Connecting it now…");
      issueKey(true);
    });

    // The content script announces on load; ask again in case this page was
    // ready first.
    window.dispatchEvent(new CustomEvent("outlier:ping-extension"));

    setTimeout(function () {
      if (extensionSeen) return;
      say(connectCopy,
        "No extension detected on this page. Install it from the Capture page, " +
        "then reload here — or connect manually below.");
    }, 1200);

    window.addEventListener("outlier:connect-result", function (event) {
      var detail = event.detail || {};
      if (connectBtn) {
        connectBtn.disabled = false;
        connectBtn.textContent = "Reconnect";
      }
      if (detail.ok) {
        say(connectMsg,
          "Connected. The extension will send captures to " + detail.endpoint +
          " — reload any open Facebook tabs.", "msg-line ok");
      } else {
        say(connectMsg, detail.error || "The extension didn't accept it.",
            "msg-line error");
      }
    });

    // The connect block runs on EVERY page so the extension can be handed a
    // key wherever the user happens to be, but the button itself only exists
    // on Capture and Account. Calling addEventListener on null threw, and
    // because this file is one IIFE, that killed every handler defined after
    // it — the pricing page's plan toggle and its checkout button among them.
    if (connectBtn) {
      connectBtn.addEventListener("click", function () { issueKey(false); });
    }
  }

  var rotateKey = document.getElementById("rotate-key");
  if (rotateKey) {
    var rotateMsg = document.getElementById("rotate-msg");
    rotateKey.addEventListener("click", function () {
      var warning = [
        "Generate a new key?",
        "",
        "The current one stops working immediately, and any extension using",
        "it must be updated."
      ].join("\n");
      if (!window.confirm(warning)) return;

      rotateMsg.className = "msg-line";
      rotateMsg.textContent = "Generating…";

      post("/api/account/rotate-key")
        .then(function (data) {
          if (!data.ok) throw new Error(data.error || "Could not rotate the key");
          document.getElementById("new-key").textContent = data.api_key;
          document.getElementById("new-key-row").style.display = "flex";
          rotateMsg.className = "msg-line ok";
          rotateMsg.textContent = "New key ready — copy it into the extension now.";
        })
        .catch(function (error) {
          rotateMsg.className = "msg-line error";
          rotateMsg.textContent = error.message;
        });
    });
  }

  var savePassword = document.getElementById("save-password");
  if (savePassword) {
    var pwMsg = document.getElementById("pw-msg");
    savePassword.addEventListener("click", function () {
      var current = document.getElementById("pw-current").value;
      var next = document.getElementById("pw-new").value;
      if (!current || !next) {
        pwMsg.className = "msg-line error";
        pwMsg.textContent = "Fill in both fields.";
        return;
      }

      pwMsg.className = "msg-line";
      pwMsg.textContent = "Updating…";

      post("/api/account/password", { current: current, new: next })
        .then(function (data) {
          if (!data.ok) throw new Error(data.error || "Could not update");
          pwMsg.className = "msg-line ok";
          pwMsg.textContent = "Password updated.";
          document.getElementById("pw-current").value = "";
          document.getElementById("pw-new").value = "";
        })
        .catch(function (error) {
          pwMsg.className = "msg-line error";
          pwMsg.textContent = error.message;
        });
    });
  }

  /* ------------------------------------------------------------ pricing */

  var intervalTabs = document.querySelectorAll(".interval-tab");
  if (intervalTabs.length) {
    intervalTabs.forEach(function (tab) {
      tab.addEventListener("click", function () {
        var interval = tab.dataset.interval;
        intervalTabs.forEach(function (t2) { t2.classList.remove("active"); });
        tab.classList.add("active");
        document.querySelectorAll(".price-option").forEach(function (option) {
          option.style.display = option.dataset.interval === interval ? "" : "none";
        });
        // The badge belongs to the yearly price, not to the tier. Picking one
        // of two tiers is not a recommendation; two months free is a fact.
        var flag = document.getElementById("price-flag");
        if (flag) flag.hidden = interval !== "year";
        var cta = document.getElementById("checkout-btn");
        if (cta) cta.dataset.interval = interval;
      });
    });
  }

  var checkoutBtn = document.getElementById("checkout-btn");
  if (checkoutBtn) {
    var checkoutMsg = document.getElementById("checkout-msg");
    checkoutBtn.addEventListener("click", function () {
      checkoutBtn.disabled = true;
      checkoutMsg.className = "msg-line";
      checkoutMsg.textContent = "Opening secure checkout…";

      post("/billing/checkout/" + checkoutBtn.dataset.interval)
        .then(function (data) {
          if (!data.ok) throw new Error(data.error || "Checkout unavailable");
          // Card details are entered on Stripe's domain, never here.
          window.location.href = data.url;
        })
        .catch(function (error) {
          checkoutBtn.disabled = false;
          checkoutMsg.className = "msg-line error";
          checkoutMsg.textContent = error.message;
        });
    });
  }

  /* ------------------------------------------------------------ remix */

  var remixBtn = document.getElementById("remix-btn");
  if (remixBtn) {
    document.querySelectorAll(".remix-hooks .hook-card").forEach(function (card) {
      card.addEventListener("click", function () {
        var already = card.classList.contains("selected");
        document.querySelectorAll(".remix-hooks .hook-card").forEach(function (c) {
          c.classList.remove("selected");
        });
        if (!already) card.classList.add("selected");
      });
    });

    remixBtn.addEventListener("click", function () {
      var angles = Array.from(
        document.querySelectorAll('input[name="angle"]:checked')
      ).map(function (input) { return input.value; });

      if (!angles.length) {
        toast("Pick at least one angle", true);
        return;
      }

      var status = document.getElementById("remix-status");
      remixBtn.disabled = true;
      remixBtn.textContent = "Generating…";
      status.className = "remix-status";
      status.textContent = "Writing variants — this takes a few seconds.";

      var steer = document.getElementById("remix-instructions");
      // The chosen opening, same as Write sends. Clicking a selected card
      // again clears it, so "let the model decide" stays reachable.
      var chosen = document.querySelector(".remix-hooks .hook-card.selected");
      post("/api/remix/" + remixBtn.dataset.postId, {
        angles: angles,
        hook: chosen ? (chosen.dataset.hook || "") : "",
        instructions: steer ? steer.value.trim() : ""
      })
        .then(function (data) {
          if (!data.ok) throw new Error(data.error || "Remix failed");
          renderRemix(data.result);
          status.textContent = "";
          toast("Variants ready");
        })
        .catch(function (error) {
          status.className = "remix-status error";
          status.textContent = error.message;
        })
        .finally(function () {
          remixBtn.disabled = false;
          remixBtn.textContent = "Generate variants";
        });
    });
  }

  function renderRemix(result) {
    var output = document.getElementById("remix-output");
    if (!output) return;

    var wrapper = document.createElement("div");
    wrapper.className = "remix-result";

    var why = document.createElement("p");
    why.className = "why";
    var whyLabel = document.createElement("b");
    whyLabel.textContent = "Why it worked: ";
    why.appendChild(whyLabel);
    // textContent throughout — model output is never injected as HTML.
    why.appendChild(document.createTextNode(result.why_it_worked || ""));
    wrapper.appendChild(why);

    (result.variants || []).forEach(function (variant, index) {
      var id = "fresh-" + Date.now() + "-" + index;

      var block = document.createElement("div");
      block.className = "variant";
      block.style.animationDelay = (index * 90) + "ms";

      var head = document.createElement("div");
      head.className = "variant-head";

      var angle = document.createElement("span");
      angle.className = "variant-angle";
      angle.textContent = (variant.angle || "").replace(/_/g, " ");

      var copy = document.createElement("button");
      copy.className = "copy-btn";
      copy.dataset.copyTarget = id;
      copy.textContent = "Copy";

      // Same markup the server renders for a saved variant, so one delegated
      // handler drives both. The hook and body ride on the button as data.
      var graphic = document.createElement("button");
      graphic.type = "button";
      graphic.className = "graphic-btn";
      graphic.textContent = "Generate graphic";
      graphic.dataset.hook = variant.hook || variant.body || "";
      graphic.dataset.body = variant.body || "";

      head.appendChild(angle);
      head.appendChild(copy);
      head.appendChild(graphic);

      // Offered only when the page says this post actually had a graphic worth
      // echoing — the same condition the server-rendered path uses, read off
      // the page rather than guessed.
      var echoable = document.getElementById("remix-btn");
      if (echoable && echoable.dataset.graphicBrief === "1") {
        var echo = document.createElement("button");
        echo.type = "button";
        echo.className = "graphic-btn is-echo";
        echo.textContent = "Same style";
        echo.title = "Make a new graphic in the style of the one on this post";
        echo.dataset.hook = variant.hook || variant.body || "";
        echo.dataset.body = variant.body || "";
        echo.dataset.likePostId = echoable.dataset.postId || "";
        head.appendChild(echo);
      }

      var body = document.createElement("p");
      body.className = "variant-body";
      body.id = id;
      body.textContent = variant.body || "";

      block.appendChild(head);
      block.appendChild(body);
      wrapper.appendChild(block);

    });

    output.prepend(wrapper);
  }

  /* ---------------------------------------------------- score explainer */

  // A plain-language popup for the score, filled with the clicked post's own
  // numbers. Every value comes from data-* attributes the server rendered —
  // counts and the tier label — so there is no user-authored text to escape.
  (function () {
    var modal = document.getElementById("score-help");
    if (!modal) return;
    var bodyEl = document.getElementById("score-help-body");

    function commas(n) {
      var v = parseFloat(n);
      return isNaN(v) ? String(n) : v.toLocaleString("en-US");
    }

    function explainHTML(d) {
      var isComment = d.kind === "comment";
      var thing = isComment ? "comment" : "post";
      // d.kind carries the real source kind now, so a post captured from a
      // page is no longer described as scored against a group.
      var place = isComment ? "thread" : (d.kind || "group");
      var pool = isComment ? "comments in this source" : "posts in this " + place;
      var medWord = isComment ? "comment median" : place + " median";
      return (
        '<p>Every ' + thing + ' is scored against what is <b>normal for its ' + place +
          '</b> — never a global number, because ' + commas(d.typical) +
          ' is a lot in a quiet ' + place + ' and little in a busy one.</p>' +
        '<p class="sh-formula">Weighted = reactions + comments&times;3 + shares&times;5' +
          '<span>comments and shares take more than a tap, so they count for more</span></p>' +
        '<p class="sh-math"><b>' + commas(d.reactions) + '</b> + <b>' + commas(d.comments) +
          '</b>&times;3 + <b>' + commas(d.shares) + '</b>&times;5 = <b>' + commas(d.weighted) +
          '</b> weighted</p>' +
        '<p>Typical here — the <b>' + medWord + '</b> — is <b>' + commas(d.typical) +
          '</b>, the middle score of all ' + pool +
          '. The median, not the average, so one viral ' + thing + " can't skew it.</p>" +
        '<p class="sh-multiple"><b>' + commas(d.weighted) + ' &divide; ' + commas(d.typical) +
          ' = ' + d.multiple + '&times;</b> &middot; ' + (d.tier || "") + "</p>" +
        '<div class="sh-bar" aria-hidden="true"><div class="sh-bar-fill"></div>' +
          '<div class="sh-bar-notch"><span>median</span></div></div>' +
        '<p class="sh-note">On the card, the notch is that median line and the glow is ' +
          "how far this " + thing + " cleared it.</p>"
      );
    }

    function openHelp(d) {
      bodyEl.innerHTML = explainHTML(d);
      modal.hidden = false;
      document.body.classList.add("score-help-open");
    }
    function closeHelp() {
      modal.hidden = true;
      document.body.classList.remove("score-help-open");
    }

    document.addEventListener("click", function (event) {
      var trigger = event.target.closest("[data-score-info]");
      if (trigger) { event.preventDefault(); openHelp(trigger.dataset); return; }
      if (event.target.closest("[data-score-close]")) { closeHelp(); }
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && !modal.hidden) closeHelp();
    });
  })();
})();
