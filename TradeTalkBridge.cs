using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Threading.Tasks;
using System.Globalization;
using cAlgo.API;
using cAlgo.API.Internals;

namespace cAlgo.Robots
{
    [Robot(TimeZone = TimeZones.UTC, AccessRights = AccessRights.FullAccess)]
    public class TradeTalkBridge : Robot
    {
        [Parameter("Server URL", DefaultValue = "https://multi-agent-trading-bot.onrender.com")]
        public string ServerUrl { get; set; }

        [Parameter("Sync Interval (Sec)", DefaultValue = 2, MinValue = 1, MaxValue = 10)]
        public int SyncInterval { get; set; }

        [Parameter("Enable Auto Execution", DefaultValue = true)]
        public bool EnableAutoExecution { get; set; }

        [Parameter("Auto Break-Even Pips", DefaultValue = 15.0, MinValue = 5.0, MaxValue = 50.0)]
        public double AutoBreakEvenPips { get; set; }

        // --- ZERO-FAILURE CAPITAL PRESERVATION CONSTANTS ---
        private const double DAILY_DRAWDOWN_LIMIT_USD = -3.00;     // 24-Hour Circuit Breaker Loss Cutoff
        private const int MAX_ACTIVE_OPEN_POSITIONS = 1;          // Strict hard cap: Maximum 1 open trade
        private static readonly string[] ALLOWED_FOREX_PAIRS = { "EURUSD", "GBPUSD" };

        private static readonly HttpClient httpClient = new HttpClient { Timeout = TimeSpan.FromSeconds(5) };
        private readonly HashSet<string> _executedTickets = new HashSet<string>();
        private readonly Dictionary<long, double> _failedModifications = new Dictionary<long, double>();

        private double _dayStartBalance = 0.0;
        private DateTime _circuitBreakerTrippedUntil = DateTime.MinValue;

        protected override void OnStart()
        {
            ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12 | SecurityProtocolType.Tls11 | SecurityProtocolType.Tls;

            _dayStartBalance = Account.Balance;
            string assetName = "USD";
            try
            {
                if (Account.Asset != null && !string.IsNullOrEmpty(Account.Asset.Name))
                {
                    assetName = Account.Asset.Name;
                }
            }
            catch
            {
                assetName = "USD";
            }

            string envName = Account.IsLive ? "LIVE REAL FUNDS" : "DEMO (Paper / Metric Verification Mode)";

            Print("=================================================");
            Print("TradeTalk.AI - ZERO-FAILURE CAPITAL PRESERVER BRIDGE");
            Print("Environment: " + envName);
            Print("Account Number: " + Account.Number);
            Print(string.Format(CultureInfo.InvariantCulture, "Starting Balance: ${0:F2} {1} | Equity: ${2:F2}", Account.Balance, assetName, Account.Equity));
            Print(string.Format(CultureInfo.InvariantCulture, "Daily Circuit Breaker: ${0:F2} (24h Lockout)", DAILY_DRAWDOWN_LIMIT_USD));
            Print("Tradeable Instruments: EURUSD, GBPUSD (0.01 Micro Lots Only)");
            Print("Max Open Positions: " + MAX_ACTIVE_OPEN_POSITIONS);
            Print("Multi-Timeframe Alignment: 15m & 1H (EMA 20/50 Aligned, 1:2 R:R)");
            Print("Server URL: " + ServerUrl);
            Print("=================================================");

            EnsureAllPositionsProtected();
            SendTelemetry();
            Timer.Start(SyncInterval);
        }

        protected override void OnTimer()
        {
            try
            {
                // 1. Post-Execution & Open Trade Guard: Ensure position has valid SL or close immediately
                EnsureAllPositionsProtected();

                // 2. Dynamic Auto-Protection: Lock in profit to Break-Even at +15 Pips
                ApplyAutoBreakEvenProtection();

                // 3. Send live telemetry (Balance, Equity, Live Prices, Open Positions, Circuit Breaker State)
                SendTelemetry();

                // 4. Check Daily Drawdown Circuit Breaker before polling new orders
                if (IsCircuitBreakerActive())
                {
                    Print(string.Format(CultureInfo.InvariantCulture, 
                        "🚨 [CIRCUIT BREAKER ACTIVE] Daily Drawdown limit (-${0:F2}) active until {1:u}. Trading halted.", 
                        Math.Abs(DAILY_DRAWDOWN_LIMIT_USD), _circuitBreakerTrippedUntil));
                    return;
                }

                // 5. Poll & Execute pending approved orders
                if (EnableAutoExecution)
                {
                    PollOrders();
                }
            }
            catch (Exception ex)
            {
                Print("Timer exception: " + ex.Message);
            }
        }

        private double GetTotalUnrealizedPnL()
        {
            double total = 0.0;
            foreach (var pos in Positions)
            {
                total += pos.NetProfit;
            }
            return total;
        }

        private double GetTodayNetPnL()
        {
            if (_dayStartBalance <= 0) _dayStartBalance = Account.Balance;
            return (Account.Equity - _dayStartBalance);
        }

        private bool IsCircuitBreakerActive()
        {
            if (DateTime.UtcNow < _circuitBreakerTrippedUntil)
            {
                return true;
            }

            double todayNet = GetTodayNetPnL();
            double unrealized = GetTotalUnrealizedPnL();

            if (todayNet <= DAILY_DRAWDOWN_LIMIT_USD || unrealized <= DAILY_DRAWDOWN_LIMIT_USD)
            {
                _circuitBreakerTrippedUntil = DateTime.UtcNow.AddHours(24);
                Print(string.Format(CultureInfo.InvariantCulture, 
                    "🚨 [CIRCUIT BREAKER TRIPPED] Net Daily PnL: ${0:F2} <= ${1:F2}. Halting all trading for 24 hours until {2:u}.", 
                    todayNet, DAILY_DRAWDOWN_LIMIT_USD, _circuitBreakerTrippedUntil));
                return true;
            }

            return false;
        }

        /// <summary>
        /// Scans all open positions. If any position has NO Stop Loss (-- / --), attempts safe SL attachment.
        /// If SL attachment fails or is rejected, IMMEDIATELY CLOSES THE POSITION within 2 seconds.
        /// </summary>
        private void EnsureAllPositionsProtected()
        {
            try
            {
                var openPositions = new List<Position>(Positions);

                foreach (var pos in openPositions)
                {
                    if (pos.StopLoss == null || pos.StopLoss <= 0)
                    {
                        Symbol sym = Symbols.GetSymbol(pos.SymbolName) ?? Symbol;
                        int digits = sym.Digits;
                        double pipSize = sym.PipSize > 0 ? sym.PipSize : Math.Pow(10, -digits);

                        double minRequiredDistance = Math.Max(sym.Spread * 3.0, pipSize * 25.0);
                        double targetSl = 0.0;
                        double targetTp = 0.0;

                        if (pos.TradeType == TradeType.Buy)
                        {
                            targetSl = Math.Round(sym.Bid - Math.Max(minRequiredDistance, pipSize * 30.0), digits);
                            targetTp = Math.Round(sym.Ask + Math.Max(minRequiredDistance * 2.0, pipSize * 60.0), digits);
                        }
                        else
                        {
                            targetSl = Math.Round(sym.Ask + Math.Max(minRequiredDistance, pipSize * 30.0), digits);
                            targetTp = Math.Round(sym.Bid - Math.Max(minRequiredDistance * 2.0, pipSize * 60.0), digits);
                        }

                        Print(string.Format("🛡️ [Emergency SL Guard] Securing #{0} ({1} {2}): SL={3}, TP={4}", 
                            pos.Id, pos.SymbolName, pos.TradeType, targetSl, targetTp));

                        TradeResult modResult = ModifyPosition(pos, targetSl, targetTp);

                        // If modify failed, FAIL-SAFE EMERGENCY AUTO-CLOSE: NEVER leave any position unprotected
                        if (modResult == null || !modResult.IsSuccessful || pos.StopLoss == null || pos.StopLoss <= 0)
                        {
                            Print(string.Format("🚨 [ZERO-FAILURE FAIL-SAFE] Position #{0} is unprotected and SL attachment failed. Closing immediately to preserve capital!", pos.Id));
                            ClosePosition(pos);
                        }
                        else
                        {
                            Print(string.Format("✅ [Protection Verified] #{0} protected with SL: {1}, TP: {2}", pos.Id, pos.StopLoss, pos.TakeProfit));
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                Print("Position protection guard error: " + ex.Message);
            }
        }

        private void ApplyAutoBreakEvenProtection()
        {
            try
            {
                foreach (var pos in Positions)
                {
                    if (pos.Pips >= AutoBreakEvenPips)
                    {
                        Symbol posSym = Symbols.GetSymbol(pos.SymbolName) ?? Symbol;
                        double pipSize = posSym.PipSize > 0 ? posSym.PipSize : Math.Pow(10, -posSym.Digits);

                        if (pos.TradeType == TradeType.Buy)
                        {
                            double targetBe = Math.Round(pos.EntryPrice + (1.0 * pipSize), posSym.Digits);
                            if (targetBe < (posSym.Bid - (posSym.Spread * 3.0)))
                            {
                                if (pos.StopLoss == null || pos.StopLoss < pos.EntryPrice)
                                {
                                    Print(string.Format("🛡️ [Auto Break-Even] Locking Profit for #{0} (+{1:F1} Pips)! SL -> {2:F5}", pos.Id, pos.Pips, targetBe));
                                    ModifyPosition(pos, targetBe, pos.TakeProfit);
                                }
                            }
                        }
                        else if (pos.TradeType == TradeType.Sell)
                        {
                            double targetBe = Math.Round(pos.EntryPrice - (1.0 * pipSize), posSym.Digits);
                            if (targetBe > (posSym.Ask + (posSym.Spread * 3.0)))
                            {
                                if (pos.StopLoss == null || pos.StopLoss > pos.EntryPrice)
                                {
                                    Print(string.Format("🛡️ [Auto Break-Even] Locking Profit for #{0} (+{1:F1} Pips)! SL -> {2:F5}", pos.Id, pos.Pips, targetBe));
                                    ModifyPosition(pos, targetBe, pos.TakeProfit);
                                }
                            }
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                Print("Auto-BE note: " + ex.Message);
            }
        }

        private async void SendTelemetry()
        {
            try
            {
                string url = ServerUrl.TrimEnd('/') + "/api/cbot/stream";
                string assetName = (Account.Asset != null && !string.IsNullOrEmpty(Account.Asset.Name)) ? Account.Asset.Name : "USD";
                string broker = Account.BrokerName ?? "IC Markets cTrader";
                string symClean = Symbol.Name.Replace("m", "").Replace(".pro", "").Replace("_i", "").ToUpperInvariant();

                StringBuilder positionsJson = new StringBuilder("[");
                int count = 0;
                foreach (var pos in Positions)
                {
                    if (count > 0) positionsJson.Append(",");
                    bool isBe = false;
                    if (pos.StopLoss != null)
                    {
                        if (pos.TradeType == TradeType.Buy && pos.StopLoss >= pos.EntryPrice) isBe = true;
                        if (pos.TradeType == TradeType.Sell && pos.StopLoss <= pos.EntryPrice) isBe = true;
                    }

                    positionsJson.Append(string.Format(
                        CultureInfo.InvariantCulture,
                        "{{\"id\":{0},\"symbol\":\"{1}\",\"trade_type\":\"{2}\",\"volume\":{3},\"entry_price\":{4},\"net_profit\":{5},\"pips\":{6},\"sl\":{7},\"tp\":{8},\"be_active\":{9}}}",
                        pos.Id, pos.SymbolName, pos.TradeType, pos.VolumeInUnits, pos.EntryPrice, pos.NetProfit, pos.Pips, pos.StopLoss ?? 0, pos.TakeProfit ?? 0, isBe ? "true" : "false"
                    ));
                    count++;
                }
                positionsJson.Append("]");

                string jsonPayload = string.Format(
                    CultureInfo.InvariantCulture,
                    "{{\"account_id\":\"{0}\",\"accountNumber\":\"{0}\",\"is_live\":{1},\"account_type\":\"{2}\",\"balance\":{3},\"equity\":{4},\"margin\":{5},\"freeMargin\":{6},\"currency\":\"{7}\",\"broker\":\"{8}\",\"symbol\":\"{9}\",\"bid\":{10},\"ask\":{11},\"live_price\":{10},\"open_positions\":{12}}}",
                    Account.Number,
                    Account.IsLive ? "true" : "false",
                    Account.IsLive ? "LIVE" : "DEMO",
                    Account.Balance,
                    Account.Equity,
                    Account.Margin,
                    Account.FreeMargin,
                    assetName,
                    broker,
                    symClean,
                    Symbol.Bid,
                    Symbol.Ask,
                    positionsJson.ToString()
                );

                var content = new StringContent(jsonPayload, Encoding.UTF8, "application/json");
                var res = await httpClient.PostAsync(url, content);
                
                if (res.IsSuccessStatusCode && EnableAutoExecution)
                {
                    string replyJson = await res.Content.ReadAsStringAsync();
                    if (!string.IsNullOrEmpty(replyJson) && (replyJson.Contains("\"pending_orders\"") || replyJson.Contains("\"ticket_id\"") || replyJson.Contains("\"signal\"")))
                    {
                        BeginInvokeOnMainThread(() => ProcessOrders(replyJson));
                    }
                }
            }
            catch (Exception ex)
            {
                Print("Telemetry send note: " + ex.Message);
            }
        }

        private async void PollOrders()
        {
            try
            {
                string url = ServerUrl.TrimEnd('/') + "/api/cbot/orders";
                var response = await httpClient.GetAsync(url);
                if (response.IsSuccessStatusCode)
                {
                    string jsonResponse = await response.Content.ReadAsStringAsync();
                    if (!string.IsNullOrEmpty(jsonResponse) && jsonResponse != "[]")
                    {
                        if (jsonResponse.Contains("\"action\":\"CLOSE\""))
                        {
                            BeginInvokeOnMainThread(() => ProcessCloseCommand(jsonResponse));
                        }
                        else if (jsonResponse.Contains("symbol"))
                        {
                            BeginInvokeOnMainThread(() => ProcessOrders(jsonResponse));
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                Print("Order poll error: " + ex.Message);
            }
        }

        private void ProcessCloseCommand(string json)
        {
            try
            {
                long posId = 0;
                long.TryParse(ExtractJsonValue(json, "position_id"), NumberStyles.Any, CultureInfo.InvariantCulture, out posId);
                if (posId > 0)
                {
                    foreach (var pos in Positions)
                    {
                        if (pos.Id == posId)
                        {
                            Print("🚨 [TradeTalk Close Command] Closing Position #" + posId + " with Net Profit: $" + pos.NetProfit);
                            ClosePosition(pos);
                            break;
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                Print("Close command error: " + ex.Message);
            }
        }

        private void ProcessOrders(string json)
        {
            try
            {
                string symbolStr = ExtractJsonValue(json, "symbol");
                string action = ExtractJsonValue(json, "signal");
                if (string.IsNullOrEmpty(action)) action = ExtractJsonValue(json, "action");
                action = action.ToUpperInvariant();

                string signalId = ExtractJsonValue(json, "ticket_id");
                if (string.IsNullOrEmpty(signalId)) signalId = ExtractJsonValue(json, "id");

                if (string.IsNullOrEmpty(symbolStr) || string.IsNullOrEmpty(action) || (action != "BUY" && action != "SELL"))
                {
                    return;
                }

                if (!string.IsNullOrEmpty(signalId) && _executedTickets.Contains(signalId))
                {
                    return;
                }

                // --- 1. DAILY CIRCUIT BREAKER CHECK ---
                if (IsCircuitBreakerActive())
                {
                    Print("🚫 [Execution Aborted] Daily Drawdown Circuit Breaker active. New orders blocked.");
                    return;
                }

                // --- 2. CAPACITY LIMIT CHECK: STRICT MAX 1 OPEN POSITION ---
                if (Positions.Count >= MAX_ACTIVE_OPEN_POSITIONS)
                {
                    Print(string.Format("🚫 [Execution Aborted] Max Open Positions ({0}) reached. Currently open: {1}.", 
                        MAX_ACTIVE_OPEN_POSITIONS, Positions.Count));
                    return;
                }

                // --- 3. TRADEABLE INSTRUMENTS WHITELIST: EURUSD & GBPUSD ONLY ---
                string cleanBaseSym = symbolStr.Replace("m", "").Replace(".pro", "").Replace("_i", "").ToUpperInvariant();
                bool isAllowedForex = false;
                foreach (var pair in ALLOWED_FOREX_PAIRS)
                {
                    if (cleanBaseSym.Contains(pair)) { isAllowedForex = true; break; }
                }

                if (!isAllowedForex)
                {
                    Print(string.Format("🚫 [Execution Aborted] {0} is prohibited. Zero-Failure rules permit EURUSD and GBPUSD only.", symbolStr));
                    return;
                }

                Symbol targetSymbol = ResolveBrokerSymbol(symbolStr);
                if (targetSymbol == null)
                {
                    Print("❌ Error: Broker symbol not found for " + symbolStr);
                    return;
                }

                // --- 4. ANTI-HEDGING & SINGLE DIRECTION RULE ---
                foreach (var openPos in Positions)
                {
                    string openClean = openPos.SymbolName.Replace("m", "").Replace(".pro", "").Replace("_i", "").ToUpperInvariant();
                    if (openClean.Contains(cleanBaseSym) || cleanBaseSym.Contains(openClean))
                    {
                        Print("🚫 [Execution Aborted] Position already active on " + targetSymbol.Name + ". Opposing / Hedging trades prohibited.");
                        return;
                    }
                }

                TradeType tradeType = (action == "BUY") ? TradeType.Buy : TradeType.Sell;

                // Micro Lot 0.01 strictly
                double lotSize = 0.01;
                double volumeInUnits = targetSymbol.NormalizeVolumeInUnits(lotSize * 100000);

                double rawSl = 0;
                double.TryParse(ExtractJsonValue(json, "sl"), NumberStyles.Any, CultureInfo.InvariantCulture, out rawSl);
                double rawTp = 0;
                double.TryParse(ExtractJsonValue(json, "tp"), NumberStyles.Any, CultureInfo.InvariantCulture, out rawTp);

                int digits = targetSymbol.Digits;
                double pipSize = targetSymbol.PipSize > 0 ? targetSymbol.PipSize : Math.Pow(10, -digits);

                // Pre-calculate broker-compliant SL & TP
                double minDistance = Math.Max(targetSymbol.Spread * 3.0, pipSize * 25.0);
                double currentRefPrice = (tradeType == TradeType.Buy) ? targetSymbol.Ask : targetSymbol.Bid;
                double validSl = rawSl;
                double validTp = rawTp;

                if (tradeType == TradeType.Buy)
                {
                    if (validSl <= 0 || validSl >= (targetSymbol.Bid - minDistance))
                    {
                        validSl = targetSymbol.Bid - Math.Max(minDistance, pipSize * 30.0);
                    }
                    if (validTp <= 0 || validTp <= (targetSymbol.Ask + minDistance))
                    {
                        validTp = targetSymbol.Ask + Math.Max(minDistance * 2.0, pipSize * 60.0);
                    }
                }
                else
                {
                    if (validSl <= 0 || validSl <= (targetSymbol.Ask + minDistance))
                    {
                        validSl = targetSymbol.Ask + Math.Max(minDistance, pipSize * 30.0);
                    }
                    if (validTp <= 0 || validTp >= (targetSymbol.Bid - minDistance))
                    {
                        validTp = targetSymbol.Bid - Math.Max(minDistance * 2.0, pipSize * 60.0);
                    }
                }

                validSl = Math.Round(validSl, digits);
                validTp = Math.Round(validTp, digits);

                double slPips = Math.Round(Math.Abs(currentRefPrice - validSl) / pipSize, 1);
                double tpPips = Math.Round(Math.Abs(validTp - currentRefPrice) / pipSize, 1);

                // Verify valid protection before sending order
                if (slPips <= 0 || tpPips <= 0)
                {
                    Print("🚫 [Pre-Validation Failed] Invalid SL/TP pips. Aborting execution.");
                    return;
                }

                Print(string.Format("🎯 [Zero-Failure Execution] Sending {0} {1} ({2} Units | SL: {3} ({4} Pips) | TP: {5} ({6} Pips))...", 
                    action, targetSymbol.Name, volumeInUnits, validSl, slPips, validTp, tpPips));

                // --- 5. EXECUTE ORDER WITH PRE-ATTACHED SL & TP ONLY ---
                TradeResult result = ExecuteMarketOrder(tradeType, targetSymbol.Name, volumeInUnits, "TradeTalk.AI", slPips, tpPips);

                // ZERO-FAILURE RULE: If broker returns any error or rejects SL/TP, ABORT ENTIRELY. Never open naked position!
                if (!result.IsSuccessful || result.Position == null)
                {
                    Print("🚨 [Execution Aborted] Broker rejected order with attached SL/TP: " + result.Error + ". Order discarded to preserve capital.");
                    return;
                }

                Position pos = result.Position;
                if (!string.IsNullOrEmpty(signalId)) _executedTickets.Add(signalId);

                Print(string.Format("🟢 Order FILLED with Verified Protection! #{0} | Entry: {1} | SL: {2} | TP: {3}", 
                    pos.Id, pos.EntryPrice, pos.StopLoss, pos.TakeProfit));

                // Fail-Safe Verification: If SL is somehow missing on filled position, close within 2 seconds
                if (pos.StopLoss == null || pos.StopLoss <= 0)
                {
                    TradeResult modRes = ModifyPosition(pos, validSl, validTp);
                    if (modRes == null || !modRes.IsSuccessful || pos.StopLoss == null || pos.StopLoss <= 0)
                    {
                        Print("🚨 [Emergency Close] Position #" + pos.Id + " opened without verified SL. Closing immediately!");
                        ClosePosition(pos);
                        return;
                    }
                }

                // Notify TradeTalk server with authentic Position ID
                ReportOrderFilled(signalId, pos.Id, pos.EntryPrice, targetSymbol.Name, action);
            }
            catch (Exception ex)
            {
                Print("MainThread Execution Exception: " + ex.Message);
            }
        }

        private Symbol ResolveBrokerSymbol(string symbolStr)
        {
            if (string.IsNullOrEmpty(symbolStr)) return Symbol;
            string clean = symbolStr.Replace("m", "").Replace(".pro", "").Replace("_i", "").Replace("/", "").ToUpperInvariant();

            return Symbols.GetSymbol(symbolStr)
                ?? Symbols.GetSymbol(clean)
                ?? Symbols.GetSymbol(clean + "m")
                ?? Symbols.GetSymbol(clean + ".pro")
                ?? Symbols.GetSymbol(clean + "_i")
                ?? Symbols.GetSymbol(clean + "micro")
                ?? Symbol;
        }

        private async void ReportOrderFilled(string signalId, long positionId, double fillPrice, string symbol, string action)
        {
            try
            {
                string url = ServerUrl.TrimEnd('/') + "/api/cbot/order-filled";
                string jsonPayload = string.Format(
                    CultureInfo.InvariantCulture,
                    "{{\"id\":\"{0}\",\"ticket_id\":\"CT_{1}\",\"position_id\":\"{1}\",\"fill_price\":{2},\"symbol\":\"{3}\",\"action\":\"{4}\",\"status\":\"FILLED\"}}",
                    signalId, positionId, fillPrice, symbol, action
                );

                var content = new StringContent(jsonPayload, Encoding.UTF8, "application/json");
                await httpClient.PostAsync(url, content);
            }
            catch
            {
            }
        }

        private string ExtractJsonValue(string json, string key)
        {
            string search = "\"" + key + "\":";
            int idx = json.IndexOf(search, StringComparison.OrdinalIgnoreCase);
            if (idx == -1) return "";
            int start = idx + search.Length;
            while (start < json.Length && (json[start] == ' ' || json[start] == '\"')) start++;
            int end = start;
            while (end < json.Length && json[end] != '\"' && json[end] != ',' && json[end] != '}') end++;
            return json.Substring(start, end - start).Trim('\"', ' ');
        }

        protected override void OnStop()
        {
            Print("TradeTalk Bridge Stopped.");
        }
    }
}
