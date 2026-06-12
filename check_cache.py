import pandas as pd
import glob

files = glob.glob('boof_cache/*.pkl')
print(f'Found {len(files)} cache files')

if files:
    df = pd.read_pickle(files[0])
    print(f'\nFirst file: {files[0]}')
    print(f'Columns: {list(df.columns)}')
    print(f'\nFirst 2 rows:')
    print(df.head(2))
