// /zh/jinkou：进口食品与边境拒绝（与荷兰相关的部分，spec §9）。
//
// 状态：草稿（agent 搭的框架，未经审核）。outline 是建议覆盖的要点，不是事实陈述；
// 写正文时每一条事实都链接到 NVWA 页面。写完后删掉 outline，填 reviewedOn。
// 本页不汇总欧盟对华通报，不点名企业（spec §9）。
// TODO（作者）：NVWA 进口相关页面的链接还没有找到合适的，目前只有 NVWA 首页，请补充。
import type { ZhPage } from "@/lib/zh-pages";

export default {
  title: "进口食品与边境拒绝",
  navLabel: "进口",
  description: "进口到荷兰的食品由谁检查、边境拒绝（border rejection）是什么意思、进口商有哪些责任。只讲与荷兰和 NVWA 相关的部分。",
  reviewedOn: null,
  officialLinks: [
    { title: "NVWA 官方网站", url: "https://www.nvwa.nl/", lang: "nl" },
    {
      title: "登记您的食品企业（进口商同样适用）",
      url: "https://www.nvwa.nl/onderwerpen/voedselveiligheid/levensmiddelen-produceren-en-verhandelen/registratie-en-erkenning/registreer-uw-levensmiddelenbedrijf",
      lang: "nl",
    },
  ],
  sections: [
    {
      heading: "进口食品由谁检查",
      body: [],
      outline: [
        "NVWA 在荷兰入境口岸对进口食品的检查职责",
        "哪些产品在入境前需要申报和检查（以 NVWA 说明为准）",
      ],
    },
    {
      heading: "边境拒绝是什么意思",
      body: [],
      outline: [
        "边境拒绝（border rejection）的含义：货物在边境未获准进入",
        "被拒绝的货物之后怎样处理（以 NVWA 说明为准）",
        "荷兰作为通报国时，边境拒绝会出现在欧盟 RASFF 系统里；本页只解释这个概念，不汇总通报",
      ],
    },
    {
      heading: "进口商的责任",
      body: [],
      outline: ["进口商作为食品企业的登记义务", "追溯、召回和向 NVWA 报告的义务"],
    },
  ],
} satisfies ZhPage;
