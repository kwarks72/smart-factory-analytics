"""
3단계: PyTorch로 이상 탐지 (오토인코더)

아이디어 (비유):
  "정상 사진만 계속 따라 그리는 연습을 한 화가"를 상상해 보세요.
  정상 사진은 잘 따라 그리지만, 처음 보는 이상한 사진은 잘 못 따라 그립니다.
  그래서 "따라 그린 것과 원본의 차이(오차)"가 크면 이상하다고 판단합니다.

  - 10/15 이전 데이터(정상이라고 가정)로만 학습시킵니다.
  - 센서 3개(온도·진동·전류)를 넣고, 그대로 복원하게 합니다.
  - 복원 오차가 학습 때 본 최대 수준을 넘으면 "이상"으로 표시합니다.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch import nn

from common import SENSOR_COLS, add_rule_flag, load_clean

Path("output").mkdir(exist_ok=True)
torch.manual_seed(0)
np.random.seed(0)

TRAIN_END = pd.Timestamp("2026-10-15")  # 이 날짜 전까지는 정상으로 가정

_, _, sensor, _ = load_clean()
sensor = add_rule_flag(sensor)

# 1) 설비마다 값의 크기가 다르니, 설비별 "평소 평균·흩어짐"으로 맞춰 줍니다 (표준화)
train_mask = sensor["ts"] < TRAIN_END
mean = sensor[train_mask].groupby("equip_id")[SENSOR_COLS].mean()
std = sensor[train_mask].groupby("equip_id")[SENSOR_COLS].std()
x_all = (sensor[SENSOR_COLS].to_numpy() - mean.loc[sensor["equip_id"]].to_numpy()) / std.loc[
    sensor["equip_id"]
].to_numpy()
x_all = torch.tensor(x_all, dtype=torch.float32)
x_train = x_all[torch.tensor(train_mask.to_numpy())]

# 2) 작은 오토인코더: 3개 값 -> 2개로 압축 -> 다시 3개로 복원
# Tanh는 값을 -1~1 사이로 눌러 주는 함수입니다. 덕분에 평소 범위를 크게 벗어난 값은 잘 복원하지 못하고, 오차가 커집니다.
model = nn.Sequential(nn.Linear(3, 8), nn.Tanh(), nn.Linear(8, 2), nn.Tanh(), nn.Linear(2, 8), nn.Tanh(), nn.Linear(8, 3))
optimizer = torch.optim.Adam(model.parameters(), lr=0.01)
loss_fn = nn.MSELoss()

for epoch in range(300):
    optimizer.zero_grad()
    loss = loss_fn(model(x_train), x_train)  # 복원 결과와 원본의 차이
    loss.backward()
    optimizer.step()
print(f"학습 끝: 마지막 오차 {loss.item():.4f}")

# 3) 모든 시간대의 복원 오차 계산 -> 6시간 평균
with torch.no_grad():
    error = ((model(x_all) - x_all) ** 2).mean(dim=1).numpy()
sensor["ae_error"] = error
sensor["ae_error_6h"] = sensor.groupby("equip_id")["ae_error"].transform(lambda s: s.rolling(6).mean())

# 4) 기준선: 학습 기간(정상) 동안 본 6시간 평균 오차의 최댓값
threshold = sensor.loc[train_mask, "ae_error_6h"].max()
sensor["ae_flag"] = sensor["ae_error_6h"] > threshold
print(f"이상 판단 기준(오차): {threshold:.2f}")

# 5) 결과 정리: 설비별로 이상 표시된 횟수와 처음 표시된 시각
rows = []
for equip_id, g in sensor.groupby("equip_id"):
    rows.append(
        {
            "설비": equip_id,
            "AI 이상 표시(시간)": int(g["ae_flag"].sum()),
            "AI 첫 이상 시각": g.loc[g["ae_flag"], "ts"].min(),
            "규칙 기반 이상 표시(시간)": int(g["rule_flag"].sum()),
            "규칙 기반 첫 이상 시각": g.loc[g["rule_flag"], "ts"].min(),
        }
    )
result = pd.DataFrame(rows)
print(result.to_string(index=False))

result.to_csv("output/anomaly_pytorch.csv", index=False, encoding="utf-8-sig")
print("\n결과를 output/anomaly_pytorch.csv에 저장했습니다.")
