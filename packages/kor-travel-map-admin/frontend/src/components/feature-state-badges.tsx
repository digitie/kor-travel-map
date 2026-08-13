import {
  featureStateLabel,
  type FeatureLifecycleState,
  type FeaturePublicationState,
  type FeatureQualityState,
} from "@/api/features";
import { Badge } from "@/components/ui/badge";

export function FeatureStateBadges({
  lifecycleState,
  publicationState,
  qualityState,
}: {
  lifecycleState: FeatureLifecycleState;
  publicationState: FeaturePublicationState;
  qualityState: FeatureQualityState;
}) {
  return (
    <>
      <Badge
        variant={lifecycleState === "retired" ? "destructive" : "secondary"}
      >
        수명: {featureStateLabel("lifecycle", lifecycleState)}
      </Badge>
      <Badge
        variant={publicationState === "published" ? "secondary" : "outline"}
      >
        공개: {featureStateLabel("publication", publicationState)}
      </Badge>
      <Badge variant={qualityState === "valid" ? "outline" : "destructive"}>
        품질: {featureStateLabel("quality", qualityState)}
      </Badge>
    </>
  );
}
