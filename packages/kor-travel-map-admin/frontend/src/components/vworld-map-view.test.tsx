// @vitest-environment jsdom
import { cleanup, render } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { VWorldMapView as SharedVWorldMapView } from "vworld-map-web";
import { VWorldMapView } from "./vworld-map-view";

vi.mock("vworld-map-web", () => ({
  VWorldMapView: vi.fn(() => null),
  useMap: () => null,
  getVWorldStyle: vi.fn(),
  getVWorldTileUrl: vi.fn(),
  getVWorldMaxZoom: vi.fn(),
  redactVWorldUrl: vi.fn(),
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function lastProps() {
  const call = vi.mocked(SharedVWorldMapView).mock.calls.at(-1);
  if (!call) throw new Error("upstream map이 렌더되지 않았습니다.");
  return call[0];
}

const center: [number, number] = [126.978, 37.5665];

it.each([undefined, "", "   ", "CHANGE_ME"])(
  "설정되지 않은 키 %s는 public mapStyle로 외부 타일 없는 지도를 사용한다",
  (apiKey) => {
    render(
      <VWorldMapView apiKey={apiKey} center={center} zoom={14} maxZoom={22} />,
    );
    expect(lastProps()).toMatchObject({
      apiKey: "",
      center,
      zoom: 14,
      maxZoom: 22,
      mapStyle: { version: 8, sources: {}, layers: [{ type: "background" }] },
    });
  },
);

it("빈 style 참조는 재렌더와 별도 지도 인스턴스 사이에서 안정적이다", () => {
  const { rerender } = render(
    <VWorldMapView apiKey="" center={center} zoom={14} />,
  );
  const initialStyle = lastProps().mapStyle;
  rerender(<VWorldMapView apiKey=" " center={[127, 37]} zoom={15} />);
  expect(lastProps().mapStyle).toBe(initialStyle);
  render(<VWorldMapView apiKey={undefined} center={center} zoom={12} />);
  expect(lastProps().mapStyle).toBe(initialStyle);
});

it("실제 키는 upstream 기본 VWorld style을 사용하고 키 변경 시 빈 style로 복귀한다", () => {
  const { rerender } = render(
    <VWorldMapView apiKey="fixture-key" center={center} zoom={14} />,
  );
  expect(lastProps().apiKey).toBe("fixture-key");
  expect(lastProps().mapStyle).toBeUndefined();
  rerender(<VWorldMapView apiKey="" center={center} zoom={14} />);
  expect(lastProps().apiKey).toBe("");
  expect(lastProps().mapStyle).toMatchObject({ sources: {} });
});
