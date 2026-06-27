"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { DatabaseIcon, PlayIcon } from "lucide-react";
import Link from "next/link";
import { useMemo } from "react";
import { useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { useEtlPreviewMutation, useProviders } from "@/api/etl";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { buttonVariants } from "@/components/ui/button-variants";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Field,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field";
import { NativeSelect } from "@/components/ui/native-select";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

const etlPreviewSchema = z.object({
  provider: z.string().min(1, "provider를 선택하세요."),
  dataset: z.string().min(1, "dataset을 선택하세요."),
  source: z.enum(["fixture", "live"]),
});

type EtlPreviewForm = z.infer<typeof etlPreviewSchema>;

function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="max-h-[38rem] overflow-auto rounded-lg bg-muted p-3 text-xs leading-relaxed">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

// dataset의 preview 가용성 라벨 (백엔드 preview: fixture/live/none).
function previewSuffix(preview: string | undefined): string {
  if (preview === "fixture") {
    return "preview: fixture";
  }
  if (preview === "live") {
    return "preview: live only";
  }
  return "preview: none";
}

export function EtlPreviewClient() {
  const providersQuery = useProviders();
  const previewMutation = useEtlPreviewMutation();

  const form = useForm<EtlPreviewForm>({
    resolver: zodResolver(etlPreviewSchema),
    defaultValues: {
      provider: "",
      dataset: "",
      source: "fixture",
    },
  });

  const provider = useWatch({
    control: form.control,
    name: "provider",
  });
  const dataset = useWatch({
    control: form.control,
    name: "dataset",
  });
  const datasets = useMemo(
    () =>
      providersQuery.data?.data.providers.find((p) => p.provider === provider)
        ?.datasets ?? [],
    [provider, providersQuery.data],
  );
  const selectedDataset = useMemo(
    () => datasets.find((entry) => entry.dataset === dataset) ?? null,
    [dataset, datasets],
  );

  const providerField = form.register("provider");
  const datasetField = form.register("dataset");
  const sourceField = form.register("source");

  const onSubmit = form.handleSubmit((values) => {
    previewMutation.mutate(values, {
      onSuccess: (data) =>
        toast.success("Preview 완료", {
          description: `${data.data.provider}/${data.data.dataset} ${data.data.items.length}건`,
        }),
      onError: (error) =>
        toast.error("Preview 실패", { description: error.message }),
    });
  });

  return (
    <main className="min-h-screen bg-muted/30">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-6 p-6">
        <header className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2">
              <Badge variant="secondary">Debug</Badge>
              <Badge variant="outline">fixture replay</Badge>
            </div>
            <h1 className="text-2xl font-semibold tracking-tight">ETL preview</h1>
            <p className="max-w-3xl text-sm text-muted-foreground">
              provider 변환 함수 출력을 적재 없이 확인합니다. form 상태는 React
              Hook Form, 값 검증은 Zod, 실행 상태는 TanStack Query mutation이
              관리합니다.
            </p>
          </div>
          <Link className={cn(buttonVariants({ variant: "outline" }))} href="/">
            홈
          </Link>
        </header>

        <div className="grid gap-4 lg:grid-cols-[24rem_1fr]">
          <Card>
            <CardHeader>
              <CardTitle>Preview 요청</CardTitle>
              <CardDescription>provider / dataset / source</CardDescription>
            </CardHeader>
            <CardContent>
              {providersQuery.isLoading ? (
                <div className="flex flex-col gap-3">
                  <Skeleton className="h-10 w-full" />
                  <Skeleton className="h-10 w-full" />
                  <Skeleton className="h-10 w-32" />
                </div>
              ) : null}

              {providersQuery.isError ? (
                <Alert variant="destructive">
                  <AlertTitle>providers 호출 실패</AlertTitle>
                  <AlertDescription>
                    {providersQuery.error.message}
                  </AlertDescription>
                </Alert>
              ) : null}

              {providersQuery.data ? (
                <form className="flex flex-col gap-5" onSubmit={onSubmit}>
                  <FieldGroup>
                    <Field
                      data-invalid={Boolean(form.formState.errors.provider)}
                    >
                      <FieldLabel htmlFor="provider">provider</FieldLabel>
                      <NativeSelect
                        id="provider"
                        aria-invalid={Boolean(form.formState.errors.provider)}
                        className="w-full"
                        {...providerField}
                        onChange={(event) => {
                          providerField.onChange(event);
                          form.setValue("dataset", "", {
                            shouldDirty: true,
                            shouldValidate: true,
                          });
                        }}
                      >
                        <NativeSelectOption value="">선택</NativeSelectOption>
                        {providersQuery.data.data.providers.map((entry) => (
                          <NativeSelectOption
                            key={entry.provider}
                            value={entry.provider}
                          >
                            {entry.provider} ({entry.datasets.length})
                          </NativeSelectOption>
                        ))}
                      </NativeSelect>
                      <FieldError
                        errors={[form.formState.errors.provider]}
                      />
                    </Field>

                    <Field data-invalid={Boolean(form.formState.errors.dataset)}>
                      <FieldLabel htmlFor="dataset">dataset</FieldLabel>
                      <NativeSelect
                        id="dataset"
                        aria-invalid={Boolean(form.formState.errors.dataset)}
                        className="w-full"
                        disabled={!provider}
                        {...datasetField}
                      >
                        <NativeSelectOption value="">선택</NativeSelectOption>
                        {datasets.map((entry) => (
                          <NativeSelectOption
                            key={entry.dataset}
                            value={entry.dataset}
                          >
                            {entry.dataset} [{entry.variant}] ·{" "}
                            {previewSuffix(entry.preview)}
                          </NativeSelectOption>
                        ))}
                      </NativeSelect>
                      <FieldDescription>
                        provider를 바꾸면 dataset 선택은 초기화됩니다. preview가
                        none이면 변환 fixture가 없어 미리보기를 만들 수 없습니다.
                      </FieldDescription>
                      {selectedDataset ? (
                        <div className="flex flex-wrap items-center gap-1.5 pt-1">
                          <Badge variant="outline">
                            {selectedDataset.feature_kind}
                          </Badge>
                          {selectedDataset.is_feature_load ? (
                            <Badge variant="secondary">feature load</Badge>
                          ) : (
                            <Badge variant="outline">value/enrichment</Badge>
                          )}
                          <Badge
                            variant={
                              selectedDataset.preview === "none"
                                ? "destructive"
                                : "outline"
                            }
                          >
                            {previewSuffix(selectedDataset.preview)}
                          </Badge>
                        </div>
                      ) : null}
                      <FieldError errors={[form.formState.errors.dataset]} />
                    </Field>

                    <Field data-invalid={Boolean(form.formState.errors.source)}>
                      <FieldLabel htmlFor="source">source</FieldLabel>
                      <NativeSelect
                        id="source"
                        aria-invalid={Boolean(form.formState.errors.source)}
                        className="w-full"
                        {...sourceField}
                      >
                        <NativeSelectOption value="fixture">
                          fixture (offline demo)
                        </NativeSelectOption>
                        <NativeSelectOption value="live">
                          live (provider client)
                        </NativeSelectOption>
                      </NativeSelect>
                      <FieldError errors={[form.formState.errors.source]} />
                    </Field>
                  </FieldGroup>

                  <Button
                    type="submit"
                    disabled={previewMutation.isPending}
                    className="w-fit"
                  >
                    <PlayIcon data-icon="inline-start" />
                    {previewMutation.isPending ? "실행 중" : "Preview 실행"}
                  </Button>
                </form>
              ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>변환 결과</CardTitle>
              <CardDescription>
                fixture 변환 결과 JSON. DB write는 수행하지 않습니다.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              {previewMutation.isPending ? (
                <Skeleton className="h-80 w-full" />
              ) : null}
              {previewMutation.isError ? (
                <Alert variant="destructive">
                  <AlertTitle>preview 실패</AlertTitle>
                  <AlertDescription>
                    {previewMutation.error.message}
                  </AlertDescription>
                </Alert>
              ) : null}
              {previewMutation.data ? (
                <div className="flex flex-col gap-3">
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <Badge>{previewMutation.data.data.provider}</Badge>
                    <Badge variant="outline">
                      {previewMutation.data.data.dataset}
                    </Badge>
                    <Badge variant="secondary">
                      {previewMutation.data.data.variant}
                    </Badge>
                    <span
                      className="text-muted-foreground"
                      data-testid="preview-count"
                    >
                      {previewMutation.data.data.items.length}건
                    </span>
                  </div>
                  <JsonBlock value={previewMutation.data.data.items} />
                </div>
              ) : (
                <div className="flex h-80 items-center justify-center rounded-lg border border-dashed text-sm text-muted-foreground">
                  <DatabaseIcon data-icon="inline-start" />
                  Preview를 실행하면 결과가 표시됩니다.
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </main>
  );
}
