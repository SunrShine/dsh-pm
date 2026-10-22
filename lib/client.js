window.__ModuleLoader__.load({
	id: "@deepseek-ai/dsh-client-ui-pm",
	factory: (require) => {
		var module = { exports: {} };
		var exports = module.exports;
		Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });
		let react_jsx_runtime = require("react/jsx-runtime");
		let react = require("react");
		//#region lib/types/client/pm-store.js
		/**
		* One shared read of the Host work-card endpoint.
		*
		* The Sidebar summary and the main panel show the same payload, so both read
		* this store instead of issuing their own request. The store is a plain
		* `getSnapshot`/`subscribe` pair because that is the shape React's
		* `useSyncExternalStore` needs; nothing else owns it.
		*/
		let state = {
			status: "idle",
			data: null,
			error: null,
			loadedAt: null
		};
		let inFlight;
		const listeners = /* @__PURE__ */ new Set();
		/** Publish one state and notify every subscriber. */
		function publish(next) {
			state = next;
			for (const listener of [...listeners]) listener();
		}
		/** Read the current snapshot. */
		function getPmCardsState() {
			return state;
		}
		/**
		* Subscribe to state changes.
		* @param listener - invalidation callback.
		* @returns the unsubscriber.
		*/
		function subscribePmCards(listener) {
			listeners.add(listener);
			return () => {
				listeners.delete(listener);
			};
		}
		/** Document-relative endpoint URL, so a mounted base path keeps working. */
		function cardsUrl(fresh) {
			return new URL(fresh ? "ui-pm/cards?refresh=1" : "ui-pm/cards", document.baseURI).href;
		}
		/** One read of the endpoint, retaining the previous payload on failure. */
		async function load(fresh) {
			if (state.data === null) publish({
				status: "loading",
				data: null,
				error: null,
				loadedAt: null
			});
			try {
				const response = await fetch(cardsUrl(fresh), { headers: { accept: "application/json" } });
				if (!(response.headers.get("content-type") ?? "").includes("application/json")) throw new Error("the Host half is not serving /ui-pm/cards yet — restart the dsh web process");
				const body = await response.json();
				if (!response.ok || body.ok !== true || body.data === void 0) throw new Error(body.error ?? `HTTP ${String(response.status)}`);
				publish({
					status: "ready",
					data: body.data,
					error: null,
					loadedAt: Date.now()
				});
			} catch (error) {
				publish({
					status: "error",
					data: state.data,
					error: error instanceof Error ? error.message : String(error),
					loadedAt: state.loadedAt
				});
			}
		}
		/**
		* Refresh the shared read, sharing one request across concurrent callers.
		* @param options - fresh request policy; the initial mount uses the Host cache.
		* @returns completion after the snapshot is published.
		*/
		function refreshPmCards(options = {}) {
			inFlight ??= load(options.fresh === true).finally(() => {
				inFlight = void 0;
			});
			return inFlight;
		}
		/**
		* Bind the shared store to a component.
		* @returns the current snapshot, re-read on every publish.
		*/
		function usePmCards() {
			return (0, react.useSyncExternalStore)(subscribePmCards, getPmCardsState, getPmCardsState);
		}
		//#endregion
		//#region lib/types/client/PmFooterSummary.js
		/**
		* One-line work-card summary in the Sidebar foot.
		*
		* This is the always-mounted surface: it tells the user whether the Host
		* endpoint answered and how many cards need attention, and it is what made the
		* first end-to-end proof of this plugin visible before the panel existed.
		*/
		/** Count the cards the panel lists. */
		function attentionCount(data) {
			if (data === null) return 0;
			return data.cards.filter((card) => card.needs_attention).length;
		}
		/**
		* Render the live work-card status line.
		* @returns a single line: loading, unavailable, or the needs-attention count.
		*/
		function PmFooterSummary() {
			const state = usePmCards();
			(0, react.useEffect)(() => {
				refreshPmCards();
			}, []);
			const text = state.status === "ready" ? `PM needs attention: ${String(attentionCount(state.data))}` : state.status === "error" ? "PM: unavailable" : "PM: …";
			return (0, react_jsx_runtime.jsx)("div", {
				"data-pm-footer-summary": "",
				title: state.error ?? state.data?.library ?? "Work-memory work cards",
				style: {
					padding: "4px 8px",
					fontSize: "12px",
					lineHeight: "1.4",
					color: state.status === "error" ? "#d98b8b" : "#7c8bff",
					whiteSpace: "nowrap",
					overflow: "hidden",
					textOverflow: "ellipsis"
				},
				children: text
			});
		}
		//#endregion
		//#region lib/types/client/PmPanel.js
		/**
		* PM workbench panel body.
		*
		* The panel is a host, not a view: the workbench itself is a static page served
		* by this plugin's node half, so the browser half only embeds it and bridges
		* the one interaction the page cannot perform for itself — opening a Session.
		* That bridge reuses the same Host probe and fallbacks every other card path
		* uses, so an archived or foreign Session is still explained rather than
		* silently ignored.
		*/
		/** Message type the workbench posts to its host. */
		const OPEN_SESSION = "pm-open-session";
		/** Instance label used when the workbench omits the field. */
		const UNKNOWN_INSTANCE = "unknown";
		/**
		* Read one workbench bridge message.
		* @param data - the message payload as received.
		* @returns the request, or null when the message is not one this panel serves.
		*/
		function bridgeRequest(data) {
			if (typeof data !== "object" || data === null) return null;
			const message = data;
			if (message.type !== OPEN_SESSION) return null;
			if (typeof message.sessionId !== "string" || message.sessionId === "") return null;
			return {
				sessionId: message.sessionId,
				instance: typeof message.instance === "string" && message.instance !== "" ? message.instance : UNKNOWN_INSTANCE
			};
		}
		/** Base used when there is no document to resolve against (server render, tests). */
		const NO_DOCUMENT_BASE = "http://localhost/";
		/**
		* Document-relative URL of the hosted workbench.
		* @param base - document base URI to resolve against.
		* @returns the workbench URL, so a mounted base path keeps working.
		*/
		function workbenchUrl(base) {
			const resolved = base ?? (typeof document === "undefined" ? NO_DOCUMENT_BASE : document.baseURI);
			return new URL("ui-pm/app/", resolved).href;
		}
		/** Panel shell: the workbench fills it, with a floor so the frame cannot collapse. */
		const shell = {
			display: "flex",
			flexDirection: "column",
			gap: "8px",
			height: "100%",
			minHeight: "560px",
			padding: "8px"
		};
		const noticeStyle = {
			fontSize: "12px",
			color: "#d9c48b",
			margin: 0
		};
		const frameStyle = {
			flex: "1 1 auto",
			width: "100%",
			minHeight: "520px",
			border: "0",
			borderRadius: "8px",
			background: "transparent"
		};
		/**
		* Render the embedded PM workbench and bridge its Session requests.
		* @param props.openSession - injected Session navigation.
		* @returns the panel body.
		*/
		function PmPanel({ openSession }) {
			const frame = (0, react.useRef)(null);
			const [notice, setNotice] = (0, react.useState)(null);
			const [busy, setBusy] = (0, react.useState)(false);
			(0, react.useEffect)(() => {
				const listener = (event) => {
					if (event.source !== frame.current?.contentWindow) return;
					const request = bridgeRequest(event.data);
					if (request === null) return;
					setBusy(true);
					setNotice(null);
					openSession(request.sessionId, request.instance).then((outcome) => {
						setNotice(outcome);
					}).finally(() => {
						setBusy(false);
					});
				};
				window.addEventListener("message", listener);
				return () => {
					window.removeEventListener("message", listener);
				};
			}, [openSession]);
			return (0, react_jsx_runtime.jsxs)("div", {
				style: shell,
				"data-pm-panel": "",
				"data-pm-view": "workbench",
				children: [(notice !== null || busy) && (0, react_jsx_runtime.jsx)("p", {
					style: noticeStyle,
					role: "status",
					"data-pm-notice": "",
					children: busy ? "Opening the Session…" : notice
				}), (0, react_jsx_runtime.jsx)("iframe", {
					ref: frame,
					"data-pm-frame": "",
					title: "PM workbench",
					src: workbenchUrl(),
					sandbox: "allow-scripts allow-same-origin allow-forms allow-modals",
					style: frameStyle
				})]
			});
		}
		//#endregion
		//#region lib/types/client/PmPanelIcon.js
		/** Decorative sidebar icon for the work-card panel row. */
		/**
		* Render the panel glyph at the size the Sidebar requests; the Sidebar owns the
		* navigation label, so the glyph itself is decorative.
		* @param props.size - requested square edge in pixels.
		* @returns the card-stack glyph.
		*/
		function PmPanelIcon({ size }) {
			return (0, react_jsx_runtime.jsxs)("svg", {
				width: size,
				height: size,
				viewBox: "0 0 16 16",
				fill: "none",
				"aria-hidden": "true",
				focusable: "false",
				children: [
					(0, react_jsx_runtime.jsx)("rect", {
						x: "2",
						y: "2.5",
						width: "12",
						height: "3.6",
						rx: "1.1",
						stroke: "currentColor",
						strokeWidth: "1.3"
					}),
					(0, react_jsx_runtime.jsx)("rect", {
						x: "2",
						y: "7.4",
						width: "12",
						height: "3.6",
						rx: "1.1",
						stroke: "currentColor",
						strokeWidth: "1.3"
					}),
					(0, react_jsx_runtime.jsx)("path", {
						d: "M4.4 13.3h7.2",
						stroke: "currentColor",
						strokeWidth: "1.3",
						strokeLinecap: "round"
					})
				]
			});
		}
		//#endregion
		//#region lib/types/client/session-open.js
		/**
		* Session navigation for one work card.
		*
		* A work-memory card names a Session that the running page may not have loaded.
		* Neither projection is an existence test: `sessions.list.ids` is the loaded
		* catalog window (older Sessions arrive by paging), and a Workspace's
		* `sessionIds` only accounts for Sessions the catalog already holds. So a card
		* outside the window is probed against the Host by retaining its exact
		* generation and awaiting the shared open attempt, and only a refused open is
		* reported as one — never as "another instance".
		*/
		/**
		* Classify one Session id against the current projections.
		* @param id - Session a work card names.
		* @param sessions - current Session list projection.
		* @param workspaces - current Workspace and archive projection.
		* @returns whether the id is loaded, archived, still loading, or merely absent from the window.
		*/
		function sessionLinkState(id, sessions, workspaces) {
			if (sessions.phase === "pending" || workspaces.phase === "pending") return "loading";
			if (workspaces.archivedSessionIds.includes(id)) return "archived";
			if (sessions.ids.includes(id)) return "available";
			return "not-loaded";
		}
		/** Message of an unknown throw. */
		function messageOf(error) {
			return error instanceof Error ? error.message : String(error);
		}
		/** The Workspace that accounts for one Session, when one does. */
		function owningWorkspace(feeds, id) {
			const owner = feeds.workspaces().items.find((item) => item.sessionIds.includes(id));
			return owner === void 0 ? void 0 : {
				workspaceId: owner.workspaceId,
				title: owner.title
			};
		}
		/**
		* Open the Session one work card names.
		*
		* A loaded, unarchived Session opens directly. Anything else is first probed
		* against the Host, which is what lets an older Session outside the loaded
		* window open normally; only after the Host refuses is the Workspace that
		* accounts for the card tried, and only after that does the click report a
		* failure — with the refusal it actually received.
		* @param nav - Workspace navigation verbs.
		* @param feeds - current Session and Workspace projections.
		* @param probe - authoritative Host existence probe.
		* @param id - Session id from the work card, as the contract spells it.
		* @returns what happened, so the caller can either stay quiet or explain.
		*/
		async function openCardSession(nav, feeds, probe, id) {
			const target = id;
			const state = sessionLinkState(target, feeds.sessions(), feeds.workspaces());
			if (state === "loading") return { kind: "loading" };
			if (state === "archived") return { kind: "archived" };
			if (state === "available") {
				nav.openSession(target);
				return { kind: "opened" };
			}
			const refusal = await probe.open(id);
			if (refusal === null) {
				nav.openSession(target);
				return { kind: "loaded" };
			}
			const owner = owningWorkspace(feeds, target);
			if (owner !== void 0) {
				try {
					await nav.openWorkspace(owner.workspaceId);
				} catch (error) {
					return {
						kind: "failed",
						detail: `connecting Workspace "${owner.title}" failed: ${messageOf(error)}`
					};
				}
				const after = sessionLinkState(target, feeds.sessions(), feeds.workspaces());
				if (after === "available") {
					nav.openSession(target);
					return { kind: "workspace-opened" };
				}
				if (after === "archived") return { kind: "archived" };
			}
			return {
				kind: "unknown",
				detail: refusal
			};
		}
		/**
		* Explain one outcome in user-facing terms, stating only what is known.
		* @param outcome - result of {@link openCardSession}.
		* @param sessionId - the Session the click targeted.
		* @param instance - work-memory instance that recorded the card.
		* @returns the notice text, or null when navigation succeeded silently.
		*/
		function openOutcomeNotice(outcome, sessionId, instance) {
			switch (outcome.kind) {
				case "opened":
				case "loaded":
				case "workspace-opened": return null;
				case "loading": return "The Session list is still loading; try again in a moment.";
				case "archived": return `Session ${sessionId} is archived; unarchive it in the Sidebar to open it.`;
				case "failed": return outcome.detail;
				case "unknown": return `Session ${sessionId} is not in the loaded Session list and the Host could not open it (${outcome.detail}). It may be a Session of another DSH instance — this card was recorded by "${instance}" — or it may no longer exist. Open the DSH instance that recorded the card, or check the Session id.`;
			}
		}
		//#endregion
		//#region lib/types/client/index.js
		/**
		* Browser half of the work-memory (PM) panel.
		*
		* The main column hosts the static PM workbench (served by the node half at
		* /ui-pm/app/) and bridges the Session requests it posts back, the Sidebar
		* panel row opens that panel, and the Sidebar foot carries an always-visible
		* needs-attention count read from the same payload the workbench fetches. Every
		* navigation outcome is explained in the panel — a card whose Session belongs to
		* another DSH instance must say so rather than look like a dead click.
		*/
		/** Main-panel key this package owns. */
		const PANEL_ID = "pm";
		/** Required services: the slot registry, Session/Workspace feeds, and Workspace navigation. */
		const inject = [
			"slots",
			"sessions",
			"workspaces",
			"uiWorkspace"
		];
		/**
		* Register the panel, its Sidebar row, and the Sidebar-foot count.
		* @param ctx - browser services used by these contributions.
		*/
		function apply(ctx) {
			const nav = {
				openSession: (sessionId) => {
					ctx.uiWorkspace.openSession(sessionId);
				},
				openWorkspace: (workspaceId) => ctx.uiWorkspace.openWorkspace(workspaceId)
			};
			const feeds = {
				sessions: () => ctx.sessions.list.getSnapshot(),
				workspaces: () => ctx.workspaces.list.getSnapshot()
			};
			const probe = { open: async (sessionId) => {
				let reference;
				try {
					reference = ctx.sessions.retain(sessionId, { source: "controllerOperation" });
				} catch (error) {
					return error instanceof Error ? error.message : String(error);
				}
				try {
					await reference.ready;
					const snapshot = reference.binding.session.getSnapshot();
					if (snapshot.openState === "open") return null;
					const refusal = snapshot.openError;
					return refusal === null ? `the Session could not be opened (state: ${snapshot.openState})` : `${refusal.code}: ${refusal.message}`;
				} catch (error) {
					return error instanceof Error ? error.message : String(error);
				} finally {
					reference.release();
				}
			} };
			ctx.slots.inject("main", () => ctx.slots.register({
				name: "main",
				key: PANEL_ID,
				inject: () => ({ openSession: async (sessionId, instance) => openOutcomeNotice(await openCardSession(nav, feeds, probe, sessionId), sessionId, instance) })
			}, PmPanel));
			ctx.slots.inject("sidebar.panellist", () => ctx.slots.register({
				name: "sidebar.panellist",
				id: PANEL_ID,
				order: 10,
				label: "PM 工作台"
			}, PmPanelIcon));
			ctx.slots.inject("sidebar.footer.action", () => ctx.slots.register({
				name: "sidebar.footer.action",
				id: "pm-panel",
				order: 20
			}, PmFooterSummary));
		}
		//#endregion
		exports.apply = apply;
		exports.inject = inject;
		return module.exports;
	}
});

//# sourceMappingURL=client.js.map