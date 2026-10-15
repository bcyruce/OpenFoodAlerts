// /zh/zhaohui-jinggao：收到召回或安全警告后怎么做（spec §9）。
//
// 状态：草稿（agent 搭的框架，未经审核）。outline 是建议覆盖的要点，不是事实陈述；
// 写正文时每一条事实都链接到 NVWA 页面。写完后删掉 outline，填 reviewedOn。
// officialLinks 是 agent 从 NVWA sitemap（2026-10）挑的候选链接，请逐个打开核对。
import type { ZhPage } from "@/lib/zh-pages";

export default {
  title: "收到召回或安全警告后怎么做",
  navLabel: "召回与警告",
  description: "NVWA 安全警告（veiligheidswaarschuwing）是什么、店里有被召回的产品时怎么做、企业的报告义务，以及怎样及时收到警告。",
  reviewedOn: null,
  officialLinks: [
    {
      title: "NVWA 安全警告（veiligheidswaarschuwingen）",
      url: "https://www.nvwa.nl/actueel/veiligheidswaarschuwingen",
      lang: "nl",
    },
    {
      title: "企业向 NVWA 报告（melden）",
      url: "https://www.nvwa.nl/onderwerpen/zaken-regelen/melden/ondernemers",
      lang: "nl",
    },
    {
      title: "订阅 NVWA 的新闻、行业通知和安全警告",
      url: "https://www.nvwa.nl/abonneren",
      lang: "nl",
    },
  ],
  sections: [
    {
      heading: "安全警告是什么",
      body: [],
      outline: [
        "NVWA 在什么情况下发布安全警告（veiligheidswaarschuwing）",
        "一条警告通常包含哪些信息：产品名称、批次、保质期、问题",
        "在哪里查看全部警告",
      ],
    },
    {
      heading: "店里有被召回的产品时",
      body: [],
      outline: [
        "按警告和供应商的说明处理：停止使用和销售、单独存放",
        "联系供应商；保留记录",
      ],
    },
    {
      heading: "企业的报告义务",
      body: [],
      outline: [
        "企业发现自己经营的食品可能不安全时，向 NVWA 报告的义务（meldplicht）",
        "怎样报告：NVWA 的报告页面",
      ],
    },
    {
      heading: "及时收到警告",
      body: [],
      outline: [
        "NVWA 官方的订阅方式",
        "本站的[中文订阅](/zh/alerts)：只含 NVWA 警告，附 AI 生成的中文摘要，以官方原文为准",
      ],
    },
  ],
} satisfies ZhPage;
