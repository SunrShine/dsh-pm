import { PmPanelIcon } from "./PmPanelIcon.js";
/** This implementation's identity in the tab system, and the key its body registers under. */
export const PM_RIGHT_ID = '@deepseek-ai/dsh-client-ui-pm';
/** Page-type discriminator used by `sidebarRight.openTab('pm')`. */
export const PM_RIGHT_KIND = 'pm';
/**
 * The PM tab type's registry definition: a page type (it recognizes no resource
 * address) whose guide entry is the discoverable way to open it.
 * @param t - namespace-bound translate, read fresh on every title call.
 * @returns the definition to register.
 */
export function pmRightTab(t) {
    return {
        id: PM_RIGHT_ID,
        kind: PM_RIGHT_KIND,
        // A：PM 页是重 iframe；切换 Session 时卸载（keepMounted:false），
        // 由 ui-pm 的 auto-open 触发器在下一个 Session 上重新打开，内存最多一份。
        keepMounted: false,
        title: () => t('right.title'),
        guide: [{
                id: 'workbench',
                order: 10,
                title: () => t('right.title'),
                description: () => t('right.description'),
                icon: PmPanelIcon,
            }],
    };
}
//# sourceMappingURL=pmRightTab.js.map