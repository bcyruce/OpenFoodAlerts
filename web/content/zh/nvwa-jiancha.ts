// /zh/nvwa-jiancha：NVWA 检查实务与 Hygiënecode（spec §9）。
//
// 状态：草稿（agent 搭的框架，未经审核）。outline 是建议覆盖的要点，不是事实陈述；
// 写正文时每一条事实都链接到 NVWA 页面。写完后删掉 outline，填 reviewedOn。
// officialLinks 是 agent 从 NVWA sitemap（2026-10）挑的候选链接，请逐个打开核对。
import type { ZhPage } from "@/lib/zh-pages";

export default {
  title: "NVWA 检查实务与卫生守则（Hygiënecode）",
  navLabel: "NVWA 检查",
  description: "NVWA 怎样检查餐饮企业、检查员关注什么、卫生守则（Hygiënecode）和 HACCP 是什么，以及检查之后会发生什么。",
  reviewedOn: null,
  officialLinks: [
    {
      title: "NVWA 的检查是怎样进行的",
      url: "https://www.nvwa.nl/ondernemers/toezicht-maatregelen-en-boetes/hoe-werkt-een-inspectie-van-de-nvwa",
      lang: "nl",
    },
    {
      title: "视频：NVWA 餐饮业检查是什么样的",
      url: "https://www.nvwa.nl/documenten/videos/2024/03/06/video-nvwa-zo-ziet-een-horeca-inspectie-eruit",
      lang: "nl",
    },
    {
      title: "视频：NVWA 餐饮业检查是什么样的",
      url: "https://www.nvwa.nl/documenten/videos/2024/03/06/video-nvwa-this-is-how-a-catering-inspection-looks-like",
      lang: "en",
    },
    {
      title: "登记您的食品企业",
      url: "https://www.nvwa.nl/onderwerpen/voedselveiligheid/levensmiddelen-produceren-en-verhandelen/registratie-en-erkenning/registreer-uw-levensmiddelenbedrijf",
      lang: "nl",
    },
    {
      title: "过敏原：给企业的工具包",
      url: "https://www.nvwa.nl/onderwerpen/voedselveiligheid/allergenen/toolkit-voor-ondernemers",
      lang: "nl",
    },
  ],
  sections: [
    {
      heading: "NVWA 是谁，检查什么",
      body: [],
      outline: [
        "NVWA（荷兰食品和消费品安全局）的职责，与市政府（gemeente）负责的营业执照等事项的区别",
        "餐饮企业在 NVWA 登记的义务",
      ],
    },
    {
      heading: "检查是怎样进行的",
      body: [],
      outline: [
        "检查是否事先通知、多久检查一次（以 NVWA 说明为准）",
        "检查员通常查看哪些方面：卫生、温度控制、过敏原信息、自查记录",
        "检查时可以怎样配合；语言不通时怎么办",
      ],
    },
    {
      heading: "卫生守则（Hygiënecode）与 HACCP",
      body: [],
      outline: [
        "什么是 Hygiënecode voor de horeca，它与 HACCP 原则的关系",
        "从哪里取得最新版本（链接官方来源）",
      ],
    },
    {
      heading: "检查之后",
      body: [],
      outline: [
        "检查后可能的结果和措施（按 NVWA 公布的执法政策说明）",
        "复查；如何对决定提出异议（bezwaar）",
        "检查结果可能被公开：见“检查结果公开”一页",
      ],
    },
  ],
} satisfies ZhPage;
