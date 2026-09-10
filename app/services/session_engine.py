from datetime import datetime, time, timezone
from typing import Dict, Any, List, Optional

class SessionEngine:
    """
    Institutional Market Session Intelligence Engine.
    Tracks Asian, London, New York, and Overlap market sessions in UTC.
    Computes session highs/lows, session opens, and session liquidity sweeps.
    """

    SESSIONS = {
        'ASIAN': {
            'name': 'Asian (Tokyo/Sydney)',
            'start_hour': 0, 'start_min': 0,
            'end_hour': 8, 'end_min': 0,
            'description': 'Liquidity & Initial Range Formation'
        },
        'LONDON': {
            'name': 'London Interbank',
            'start_hour': 7, 'start_min': 0,
            'end_hour': 15, 'end_min': 30,
            'description': 'Major Institutional Expansion & Judas Swings'
        },
        'LONDON_NY_OVERLAP': {
            'name': 'London / NY Overlap',
            'start_hour': 12, 'start_min': 30,
            'end_hour': 15, 'end_min': 30,
            'description': 'Peak Global Liquidity & Volatility'
        },
        'NEW_YORK': {
            'name': 'New York Session',
            'start_hour': 12, 'start_min': 0,
            'end_hour': 20, 'end_min': 0,
            'description': 'US Macro Trends, News Drivers & Afternoon Reversals'
        }
    }

    @classmethod
    def get_current_session_info(cls, current_dt: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Returns current active session(s), time elapsed, and trading characteristics.
        """
        if current_dt is None:
            current_dt = datetime.now(timezone.utc)
        elif current_dt.tzinfo is None:
            current_dt = current_dt.replace(tzinfo=timezone.utc)

        current_time = current_dt.time()
        active_sessions = []

        for code, conf in cls.SESSIONS.items():
            start_t = time(conf['start_hour'], conf['start_min'])
            end_t = time(conf['end_hour'], conf['end_min'])

            if start_t <= current_time <= end_t:
                active_sessions.append(code)

        # Primary session designation
        if 'LONDON_NY_OVERLAP' in active_sessions:
            primary = 'LONDON_NY_OVERLAP'
        elif 'LONDON' in active_sessions:
            primary = 'LONDON'
        elif 'NEW_YORK' in active_sessions:
            primary = 'NEW_YORK'
        elif 'ASIAN' in active_sessions:
            primary = 'ASIAN'
        else:
            primary = 'OFF_HOURS_ASIAN_LATE'

        is_high_volume_time = primary in ('LONDON', 'LONDON_NY_OVERLAP', 'NEW_YORK')

        return {
            'utc_time': current_dt.strftime('%H:%M:%S UTC'),
            'active_sessions': active_sessions,
            'primary_session': primary,
            'session_name': cls.SESSIONS.get(primary, {}).get('name', 'Off-Hours'),
            'is_high_volume_window': is_high_volume_time,
            'liquidity_rating': 'HIGH' if primary == 'LONDON_NY_OVERLAP' else ('MEDIUM' if is_high_volume_time else 'LOW')
        }

    @classmethod
    def calculate_session_levels(
        cls,
        m15_candles: List[Dict[str, Any]],
        current_dt: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Extracts session High, Low, and Open from recent candles.
        Detects if current session has swept previous session High or Low.
        """
        if not m15_candles or len(m15_candles) < 4:
            return {
                'asian_high': None,
                'asian_low': None,
                'london_high': None,
                'london_low': None,
                'sweep_detected': False,
                'sweep_details': None
            }

        asian_high = None
        asian_low = None
        london_high = None
        london_low = None

        asian_candles = []
        london_candles = []

        for c in m15_candles[-96:]:
            ts_str = str(c.get('timestamp', ''))
            try:
                if 'T' in ts_str:
                    hour = int(ts_str.split('T')[1].split(':')[0])
                elif ' ' in ts_str:
                    hour = int(ts_str.split(' ')[1].split(':')[0])
                else:
                    continue

                if 0 <= hour < 8:
                    asian_candles.append(c)
                elif 7 <= hour < 15:
                    london_candles.append(c)
            except Exception:
                continue

        if asian_candles:
            asian_high = round(max(float(c['high']) for c in asian_candles), 3)
            asian_low = round(min(float(c['low']) for c in asian_candles), 3)

        if london_candles:
            london_high = round(max(float(c['high']) for c in london_candles), 3)
            london_low = round(min(float(c['low']) for c in london_candles), 3)

        current_price = float(m15_candles[-1]['close'])
        sweep_detected = False
        sweep_details = None

        if asian_high and current_price > asian_high:
            sweep_detected = True
            sweep_details = f'Price (${current_price:.2f}) expanded beyond Asian High (${asian_high:.2f})'
        elif asian_low and current_price < asian_low:
            sweep_detected = True
            sweep_details = f'Price (${current_price:.2f}) swept below Asian Low (${asian_low:.2f})'

        return {
            'asian_high': asian_high,
            'asian_low': asian_low,
            'london_high': london_high,
            'london_low': london_low,
            'sweep_detected': sweep_detected,
            'sweep_details': sweep_details
        }

session_engine = SessionEngine()
