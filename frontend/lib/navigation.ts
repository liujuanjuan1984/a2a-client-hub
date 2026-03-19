import { type Href } from "expo-router";

import { blurActiveElement } from "@/lib/focus";

type BackOrHomeRouter = {
  canGoBack: () => boolean;
  back: () => void;
  replace: (href: Href) => void;
};

export function backOrHome(router: BackOrHomeRouter, homeHref: Href = "/") {
  blurActiveElement();
  if (router.canGoBack()) {
    router.back();
    return;
  }
  // Use replace to avoid leaving a dead-end screen in the history stack (deep link / standalone entry).
  router.replace(homeHref);
}
