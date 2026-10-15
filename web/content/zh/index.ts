// 中文模块的全部页面（spec §9，ticket 32）。每页一个文件，写法见 web/README.md 的
// "Chinese module content" 一节。新增页面：在 i18n/routing.ts 的 ZH_MODULE_PAGES 里加路径，
// 在这里登记，再建 app/[locale]/<路径>/page.tsx（照抄现有的四个）。
import type { ZhModulePage } from "@/i18n/routing";
import type { ZhPage } from "@/lib/zh-pages";
import home from "./home";
import jianchaJieguoGongkai from "./jiancha-jieguo-gongkai";
import jinkou from "./jinkou";
import nvwaJiancha from "./nvwa-jiancha";
import zhaohuiJinggao from "./zhaohui-jinggao";

/** `/zh`, the landing page of the module. */
export const ZH_HOME: ZhPage = home;

/** The guide pages, in the order of the module navigation. */
export const ZH_PAGES: Record<ZhModulePage, ZhPage> = {
  "nvwa-jiancha": nvwaJiancha,
  "zhaohui-jinggao": zhaohuiJinggao,
  "jiancha-jieguo-gongkai": jianchaJieguoGongkai,
  jinkou,
};
