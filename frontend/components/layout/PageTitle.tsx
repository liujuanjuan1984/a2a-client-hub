import Head from "expo-router/head";

type PageTitleProps = {
  title: string;
};

const APP_TITLE_SUFFIX = "A2AClientHub";

export function PageTitle({ title }: PageTitleProps): JSX.Element {
  const normalizedTitle = title.includes("|")
    ? title
    : `${title} | ${APP_TITLE_SUFFIX}`;
  return (
    <Head>
      <title>{normalizedTitle}</title>
    </Head>
  );
}

export function buildGeneratingTitle({
  baseTitle,
  isGenerating,
}: {
  baseTitle: string;
  isGenerating: boolean;
}) {
  return isGenerating ? `[Generating...] ${baseTitle}` : baseTitle;
}
