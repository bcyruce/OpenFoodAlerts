// /zh：中文模块首页。下面四个指南页的列表和订阅入口由页面自动生成，这里只写介绍文字。
//
// 状态：草稿（agent 搭的框架，未经审核）。写完或审校后：
//   1. 在 body 里写正文（段落是字符串，列表用 { list: [...] }，链接写成 [文字](https://www.nvwa.nl/...)）；
//   2. 删掉 outline；
//   3. 把 reviewedOn 改成审核当天的日期，例如 "2026-11-02"。
// 然后运行 `pnpm --dir web test zh-content` 检查。
import type { ZhPage } from "@/lib/zh-pages";

export default {
  title: "NVWA 食品安全中文指南",
  navLabel: "首页",
  description:
    "为在荷兰经营餐饮或进口食品的华人整理：NVWA 的检查、召回与安全警告、检查结果公开制度和进口说明。每页注明审核日期，并链接 NVWA 官方页面。",
  reviewedOn: null,
  officialLinks: [
    { title: "NVWA 官方网站", url: "https://www.nvwa.nl/", lang: "nl" },
    {
      title: "NVWA 安全警告（veiligheidswaarschuwingen）",
      url: "https://www.nvwa.nl/actueel/veiligheidswaarschuwingen",
      lang: "nl",
    },
  ],
  sections: [
    {
      heading: "关于本指南",
      body: [],
      outline: [
        "本指南写给谁：在荷兰开餐馆、外卖店、亚洲超市或做食品进口的华人",
        "只讲荷兰和 NVWA 的规则，不涉及其他国家",
        "本站不是官方来源，与 NVWA 无关联；一切以 NVWA 官方页面为准",
        "每页顶部的审核日期是什么意思；规则变化时以官方页面为准",
      ],
    },
  ],
} satisfies ZhPage;
