;;; pm.el --- pm work-memory 集成  -*- lexical-binding: t; -*-

;;; Commentary:
;;
;; 把 work-memory 库接进 Emacs：看板跳转、agenda、capture。
;;
;; 用法（init.el）：
;;   (setenv "PM_WORK_MEMORY" "/path/to/work-memory")
;;   (load "/path/to/pm_tools/pm.el")
;;
;; Windows 上的 Emacs 读不到 WSL 的 /home 路径，要用 UNC：
;;   \\wsl.localhost\Ubuntu\home\rui\projects\tools_dev\pm_tools\sandbox\work-memory
;;
;; 注意：agenda 只挂人工文件。generated/ 是机器生成物，没有 TODO，
;; 挂进去只会拖慢 agenda 而且毫无产出。
;;
;; 常用：
;;   M-x pm-open-dashboard   打开库根看板 index.org
;;   M-x pm-browse-cards     在 dired 里浏览全部工作卡
;;   M-x pm-open-card        按 session id 直接跳到某张卡
;;   C-c a P                 所有未完成的 pm 任务
;;
;;; Code:

(defvar pm-root
  (or (getenv "PM_WORK_MEMORY")
      (expand-file-name "~/work-memory"))
  "work-memory 库根目录。优先环境变量 PM_WORK_MEMORY；否则 ~/work-memory。")

(defvar pm-dashboard (expand-file-name "index.org" pm-root)
  "库根看板文件。")

(defvar pm-generated-dir (expand-file-name "generated" pm-root)
  "机器生成目录。")


;;; ── 多文件 inbox（2026-10-22）：人工按周/按月轮转，inbox.org 只是生成视图 ────

(defvar pm-inbox-human-mode "weekly"
  "人工 inbox 轮转粒度：weekly | monthly | single（须与 pm.toml 的 [inbox] human_mode 一致）。")

(defun pm--inbox-period-suffix ()
  "按 pm-inbox-human-mode 返回当前周期后缀（single 返回 nil）。"
  (cond ((string= pm-inbox-human-mode "single") nil)
        ((string= pm-inbox-human-mode "monthly") (format-time-string "%Y-%m"))
        (t (format-time-string "%G-W%V"))))

(defun pm-inbox-current-human-file ()
  "当前人工 inbox 文件路径（与 pm 后端 human_path 规则一致）。"
  (let ((suffix (pm--inbox-period-suffix)))
    (expand-file-name
     (if suffix (format "inbox-human-%s.org" suffix) "inbox.org")
     pm-root)))

(defun pm--inbox-generated-p (file)
  "FILE 是否是 pm 生成的汇总视图（首行附近带生成标记）。"
  (and (file-readable-p file)
       (with-temp-buffer
         (insert-file-contents file nil 0 400)
         (goto-char (point-min))
         (search-forward "由 pm 自动生成" nil t))))

(defun pm-human-inbox-files ()
  "参与 agenda/浏览的人工 inbox 文件：inbox-human-*.org + 旧的单文件 inbox.org（非生成视图）。"
  (let* ((rotated (file-expand-wildcards (expand-file-name "inbox-human-*.org" pm-root)))
         (legacy (expand-file-name "inbox.org" pm-root))
         (legacy (and (file-exists-p legacy)
                      (not (pm--inbox-generated-p legacy))
                      legacy)))
    (seq-filter #'file-exists-p (delq nil (append rotated (list legacy))))))

(defun pm-inbox-new-id ()
  "生成一个 pm 可接受的手写条目 ID。"
  (format "inbox-emacs-%s-%06x"
          (format-time-string "%Y%m%d-%H%M%S")
          (random 16777216)))

(defun pm-inbox-now ()
  "当前时间的 ISO8601（带时区偏移）。"
  (format-time-string "%Y-%m-%dT%H:%M:%S%:z"))

(defun pm-inbox-entry-snippet ()
  "返回一个最小合法 inbox 条目文本（手写/插入用）。"
  (concat
   "** INBOX \n"
   "   :PROPERTIES:\n"
   "   :ID: " (pm-inbox-new-id) "\n"
   "   :PM_KIND: inbox\n"
   "   :PM_STATUS: CAPTURED\n"
   "   :PM_SOURCE: manual\n"
   "   :PM_ADDED_BY: human\n"
   "   :PM_CAPTURED_AT: " (pm-inbox-now) "\n"
   "   :END:\n"
   "   \n"))

(defun pm-insert-inbox-entry ()
  "在当前 buffer 光标处插入一个合法 inbox 条目模板（:ID: 已生成）。"
  (interactive)
  (insert (pm-inbox-entry-snippet))
  (backward-char 2))

(defun pm-inbox-open-current ()
  "打开当前周期人工 inbox；不存在则创建带模板/说明的文件。"
  (interactive)
  (let ((file (pm-inbox-current-human-file)))
    (unless (file-exists-p file)
      (with-temp-file file
        (insert "#+TITLE: Inbox (human)\n")
        (insert "#+TODO: INBOX(i) TODO(t) NEXT(n) DOING(s) WAITING(w@) BLOCKED(b@) REVIEW(r) | DONE(d!) CANCELLED(c@)\n\n")
        (insert "* Inbox\n")
        (insert "  人工快速笔记：要纳入 pm 管理，用 M-x pm-insert-inbox-entry 插入条目模板。\n\n")
        (insert "# ==== 手动条目模板（M-x pm-insert-inbox-entry 自动插入）====\n")
        (insert "# ** INBOX 一句话标题\n")
        (insert "#    :PROPERTIES:\n")
        (insert "#    :ID: inbox-manual-<唯一ID>  :PM_KIND: inbox  :PM_STATUS: CAPTURED\n")
        (insert "#    :PM_ADDED_BY: human  :PM_CAPTURED_AT: <ISO时间>  :END:\n")))
    (find-file file)))

(defun pm--pm-binary ()
  "pm 可执行文件（默认库里 bin/pm，可用变量 pm-bin 覆盖）。"
  (or (and (boundp 'pm-bin) pm-bin)
      (let ((candidate (expand-file-name "../bin/pm" pm-root)))
        (if (file-executable-p candidate) candidate "pm"))))

(defun pm-capture-inbox (text)
  "用 pm capture 记录一条快速笔记：自动 ID/时间/审计，并按来源路由到人工文件。"
  (interactive "s记录内容: ")
  (let* ((default-directory pm-root)
         (out (with-temp-buffer
                (let ((code (call-process (pm--pm-binary) nil t nil
                                          "capture" text "--json")))
                  (unless (zerop code)
                    (error "pm capture 失败（exit %s）：%s" code (buffer-string)))
                  (buffer-string))))
         (json (ignore-errors (json-parse-string out :object-type 'alist)))
         (path (alist-get 'path json))
         (line (alist-get 'line json)))
    (message "已记录：%s:%s" path line)
    (when path
      (find-file (expand-file-name path pm-root))
      (when line (goto-char (point-min)) (forward-line (1- line))))))

(defun pm-inbox-render ()
  "重新生成 inbox.org 汇总视图（只读视图，真源是 inbox-human-*/inbox-ai-*）。"
  (interactive)
  (let ((default-directory pm-root)
        (buf (get-file-buffer (expand-file-name "inbox.org" pm-root))))
    (with-temp-buffer
      (unless (zerop (call-process (pm--pm-binary) nil t nil "inbox" "render"))
        (error "pm inbox render 失败：%s" (buffer-string))))
    (when buf (with-current-buffer buf (revert-buffer t t t)))
    (message "inbox.org 汇总视图已刷新")))

(defun pm-inbox-open-file ()
  "在人工 inbox 轮转文件里选一个打开。"
  (interactive)
  (let ((files (pm-human-inbox-files)))
    (if (null files)
        (pm-inbox-open-current)
      (find-file (completing-read "人工 inbox: " files nil t)))))

(defun pm-install-capture-template ()
  "把 pm 的 org-capture 模板（键 p）加进 org-capture-templates（写当前人工 inbox，带 :ID: 等属性）。"
  (interactive)
  (add-to-list 'org-capture-templates
               (list "p" "pm Inbox（人工，多文件）" 'entry
                     (list 'file+headline '(pm-inbox-current-human-file) "Inbox")
                     (concat "** INBOX %^{标题}\n"
                             "   :PROPERTIES:\n"
                             "   :ID: %(pm-inbox-new-id)\n"
                             "   :PM_KIND: inbox\n"
                             "   :PM_STATUS: CAPTURED\n"
                             "   :PM_SOURCE: manual\n"
                             "   :PM_ADDED_BY: human\n"
                             "   :PM_CAPTURED_AT: %(pm-inbox-now)\n"
                             "   :END:\n"
                             "%?"))
               t)
  (message "已加入 org-capture 模板：p => %s" (pm-inbox-current-human-file)))

(defvar pm-agenda-files
  (seq-filter #'file-exists-p
              (append (pm-human-inbox-files)
                      (list (expand-file-name "projects" pm-root)
                            (expand-file-name "journal" pm-root))))
  "参与 org-agenda 的人工文件与目录（inbox 只挂人工轮转文件；AI 不进 agenda）。")

(defun pm-setup-agenda-files ()
  "把 pm 的人工文件加入 agenda 文件列表。"
  (interactive)
  (dolist (file pm-agenda-files)
    (add-to-list 'org-agenda-files file)))

(defun pm-open-dashboard ()
  "打开 work-memory 看板。"
  (interactive)
  (find-file pm-dashboard))

(defun pm-browse-cards ()
  "在 dired 里浏览全部工作卡（按数据根分目录）。"
  (interactive)
  (dired (expand-file-name "sessions" pm-generated-dir)))

(defun pm-open-card (session-id)
  "打开指定会话的工作卡。SESSION-ID 可带可不带 session- 前缀。"
  (interactive "sSession id: ")
  (let* ((id (if (string-prefix-p "session-" session-id)
                 session-id
               (concat "session-" session-id)))
         (hits (directory-files-recursively
                (expand-file-name "sessions" pm-generated-dir)
                (concat "^" (regexp-quote id) "\\.org\\'"))))
    (cond ((null hits) (message "找不到工作卡：%s" id))
          ((= 1 (length hits)) (find-file (car hits)))
          (t (find-file (completing-read "选择工作卡: " hits nil t))))))

(with-eval-after-load 'org
  (pm-setup-agenda-files)
  ;; 只加一个键，避免覆盖你已有的 agenda 绑定。
  (add-to-list 'org-agenda-custom-commands
               '("P" "pm: 全部未完成"
                 todo "INBOX|TODO|NEXT|DOING|WAITING|BLOCKED|REVIEW"))
  (unless (assoc "p" org-capture-templates)
    (pm-install-capture-template)))

(provide 'pm)
;;; pm.el ends here
