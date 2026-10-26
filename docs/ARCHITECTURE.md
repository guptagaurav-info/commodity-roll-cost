# How this project works

Colour key: **blue** = external data · **lavender** = code step · **red** = check, gate or decision · **green** = good outcome · **yellow** = caution · **grey** = output

## 1. Pipeline (what `make all` runs)

```mermaid
flowchart TD
    A["SOURCE: EIA WTI + Henry Hub daily spot<br/>copy: github.com/datasets (ODC-PDDL)"]
    B["SOURCE: fund prices + distributions<br/>USO USL DBO UNG UNL GSG DBC USCI GLD SPY"]
    C["SOURCE: 3-month Treasury yield"]
    I{"ingest.py<br/>sha256 matches config?"}
    A --> I
    B --> I
    C --> I
    I -- "no" --> X["Stop: source changed"]
    I -- "yes" --> L
    subgraph L["Build returns · pipeline.py"]
      L1["Daily total return = split-adjusted close + distributions"]
      L2{"Any daily move above 50%?<br/>(unadjusted split check)"}
      L3["Month-end returns; spot month-end change; T-bill income"]
    end
    subgraph T["Tests"]
      T1["Gap = fund − spot change − T-bill income (log, annualised)"]
      T2["Front month vs 12-month strip vs optimum yield"]
      T3["Pre-specified switching rule, 1/3/6-month signals, 10 bp per switch"]
      T4["Broad baskets, 2022 and 2026 episodes"]
    end
    O["reports/metrics.json · monthly_returns.csv · figures/*.png"]
    L --> T --> O
    classDef src fill:#dbe8ff,stroke:#1f5fbf,color:#0b1f44
    classDef step fill:#ece8ff,stroke:#6b5fbf,color:#1d1640
    classDef gate fill:#ffe0e0,stroke:#c03030,color:#400000
    classDef out fill:#eeeeee,stroke:#777,color:#222
    class A,B,C src
    class L1,L3,T1,T2,T3,T4 step
    class I,X,L2 gate
    class O out
```

![Pipeline](../reports/figures/flow-1.png)

## 2. How a committee would choose the vehicle

```mermaid
flowchart TD
    Q["Mandate: strategic commodity exposure<br/>or a short-dated hedge?"]
    S["Strategic sleeve"]
    H["Tactical hedge (weeks to a few months)"]
    V["Hold 12-month strip, optimum-yield<br/>or backwardation-tilted funds"]
    F["Front month acceptable;<br/>budget the roll cost up front"]
    G{"Natural gas or another steep-contango market?"}
    N["Avoid front-month funds as a holding:<br/>−24.6% a year vs −2.8% spot"]
    M["Report monthly: fund return vs spot + T-bills<br/>(the roll gap), by vehicle"]
    R{"Gap worse than budget for 2 quarters?"}
    A["Review vehicle and size"]
    K["Keep"]
    Q --> S --> V --> G
    Q --> H --> F --> M
    G -- "yes" --> N --> M
    G -- "no" --> M
    M --> R
    R -- "yes" --> A
    R -- "no" --> K
    classDef src fill:#dbe8ff,stroke:#1f5fbf,color:#0b1f44
    classDef step fill:#ece8ff,stroke:#6b5fbf,color:#1d1640
    classDef gate fill:#ffe0e0,stroke:#c03030,color:#400000
    classDef good fill:#dff3e3,stroke:#2e8b57,color:#0f3d22
    classDef warn fill:#fff4cc,stroke:#c9a400,color:#3d3200
    class Q src
    class S,H,M step
    class G,R gate
    class V,K good
    class F,N,A warn
```

![Decision](../reports/figures/flow-2.png)
