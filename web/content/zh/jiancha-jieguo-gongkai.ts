// /zh/jiancha-jieguo-gongkai：检查结果公开制度（Gezondheidswet 第 44 条，spec §9）。
//
// 状态：草稿（agent 搭的框架，未经审核）。outline 是建议覆盖的要点，不是事实陈述；
// 写正文时每一条事实都链接到 NVWA 页面。写完后删掉 outline，填 reviewedOn。
// 本页只说明制度，不列出、不点名任何企业的检查结果（spec §9）。
// TODO（作者）：补上 Gezondheidswet 在 wetten.overheid.nl 上的链接（允许的官方域名之一）。
import type { ZhPage } from "@/lib/zh-pages";

export default {
  title: "检查结果公开制度（Gezondheidswet 第 44 条）",
  navLabel: "检查结果公开",
  description: "NVWA 依据 Gezondheidswet 第 44 条公开检查结果：法律依据、公开的流程、怎样提出意见和异议。",
  reviewedOn: null,
  officialLinks: [
    {
      title: "NVWA：餐饮、手工食品业和零售的检查结果",
      url: "https://www.nvwa.nl/onderwerpen/voedselveiligheid/inspectieresultaten-horecagelegenheden",
      lang: "nl",
    },
  ],
  sections: [
    {
      heading: "法律依据",
      body: [],
      outline: [
        "Gezondheidswet 第 44 条的内容（链接法律原文）",
        "哪些行业的检查结果会被公开（以 NVWA 说明为准）",
      ],
    },
    {
      heading: "公开的流程",
      body: [],
      outline: [
        "公开决定草案（ontwerpbesluit）和发表意见（zienswijze）的机会",
        "正式决定（besluit）之后在哪里、多久公开",
      ],
    },
    {
      heading: "提出异议",
      body: [],
      outline: [
        "异议（bezwaar）的程序和期限",
        "提出异议本身不阻止公开（“het indienen van een bezwaarschrift houdt de openbaarmaking niet tegen”，引用前核对原文）",
      ],
    },
    {
      heading: "本站不公布企业名单",
      body: [],
      outline: ["本站只说明制度，不列出也不点名任何企业的检查结果；查询结果请直接去 NVWA 的页面"],
    },
  ],
} satisfies ZhPage;
