import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch

# 1. Load the Data
csv_file = 'phase6_shmoo_data.csv'
print(f"[*] Loading data from {csv_file}...")
try:
    # Force pandas to overwrite the existing header with 5-column layout
    df = pd.read_csv(csv_file, header=0, names=['Target_MHz', 'VOS_Scale', 'Iteration', 'Status', 'Error_Type'])
except FileNotFoundError:
    print(f"[!] Could not find {csv_file}. Make sure you are in the right directory.")
    exit(1)

# 2. Map Error Types to Numerical Values for Coloring
# 0 = Pass (Green)
# 1 = Type A Vulnerability (Gold/Orange)
# 2 = Type B/C System Crash (Red)
def map_error(error):
    if pd.isna(error) or error == 'None':
        return 0
    elif 'Type A' in str(error):
        return 1
    else:
        return 2

df['Error_Code'] = df['Error_Type'].apply(map_error)

# 3. Aggregate Iterations
# If a specific VOS/MHz combo had ANY Type A errors, flag it as 1. 
# If it had no Type A but had Type C, flag it as 2. Otherwise 0.
def get_shmoo_status(series):
    if 1 in series.values:
        return 1
    elif 2 in series.values:
        return 2
    else:
        return 0

# Create the 2D Pivot Table (Grid)
# Create the 2D Pivot Table (Grid) and assume missing data is a Type C crash (Value: 2)
shmoo_grid = df.groupby(['VOS_Scale', 'Target_MHz'])['Error_Code'].agg(get_shmoo_status).unstack().fillna(2)

# 4. Build the Heatmap
# Custom Color Map: Green, Orange, Red
cmap = ListedColormap(['#2ca02c', '#ff7f0e', '#d62728']) 

plt.figure(figsize=(14, 6))
ax = sns.heatmap(shmoo_grid, cmap=cmap, cbar=False, linewidths=1, linecolor='black')

# 5. Formatting & Aesthetics
plt.title('Phase 6 Shmoo Plot: Core Frequency vs. Voltage Scale\n(HMAC-SHA256 Cryptographic Enclave)', fontsize=16, fontweight='bold', pad=15)
plt.xlabel('Core Frequency (MHz)', fontsize=14, fontweight='bold')
plt.ylabel('Voltage Scale (VOS)', fontsize=14, fontweight='bold')

# Ensure VOS 3 (High Power) is at the top, and VOS 1 (Low Power) is at the bottom
ax.invert_yaxis()

# 6. Custom Legend
legend_elements = [
    Patch(facecolor='#2ca02c', edgecolor='black', label='Pass (Stable Math)'),
    Patch(facecolor='#ff7f0e', edgecolor='black', label='Type A (Silent Data Corruption)'),
    Patch(facecolor='#d62728', edgecolor='black', label='Type B/C (System Hang / Crash)')
]
plt.legend(handles=legend_elements, loc='upper left', bbox_to_anchor=(1.02, 1), borderaxespad=0, title="Validation Status", title_fontsize=12)

# 7. Save and Render
plt.tight_layout()
output_filename = 'phase6_shmoo_plot.png'
plt.savefig(output_filename, dpi=300, bbox_inches='tight')
print(f"[*] Shmoo Plot successfully generated and saved as '{output_filename}'")
plt.show()