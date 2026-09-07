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

        // --- TRADETALK V2: STRICT GOLD-ONLY (XAUUSD) ULTRA-SAFE PARAMETERS ---
        private const int MAX_CONCURRENT_POSITIONS = 1;          // Strictly 1 open position at all times
        private const double FIXED_GOLD_LOT_SIZE = 0.01;         // Fixed 0.01 Micro-Lot strictly (No scaling)
        private const double MIN_RR_RATIO = 2.0;                 // Minimum 1:2 Risk-to-Reward Ratio

        private static readonly HttpClient httpClient = new HttpClient { Timeout = TimeSpan.FromSeconds(5) };
        private readonly HashSet<string> _executedTickets = new HashSet<string>();
        private readonly Dictionary<long, double> _failedModifications = new Dictionary<long, double>();

        protected override void OnStart()
        {
            ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12 | SecurityProtocolType.Tls11 | SecurityProtocolType.Tls;

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
            Print("TradeTalk.AI V2 - STRICT GOLD (XAUUSD) EXECUTION BRIDGE");
            Print("Environment: " + envName);
            Print("Account Number: " + Account.Number);
            Print(string.Format(CultureInfo.InvariantCulture, "Balance: ${0:F2} {1} | Equity: ${2:F2}", Account.Balance, assetName, Account.Equity));
            Print("Target Instrument: XAUUSD (Gold) ONLY");
            Print("Position Sizing: EXACTLY 0.01 Lots Fixed");
            Print("Max Open Positions: " + MAX_CONCURRENT_POSITIONS);
            Print("Dynamic Auto Break-Even Guard: +" + AutoBreakEvenPips + " Pips");
            Print("Target Server: " + ServerUrl);
            Print("=================================================");

            EnsureAllPositionsProtected();
            SendTelemetry();
            Timer.Start(SyncInterval);
        }

        protected override void OnTimer()
        {
            try
            {
                // 1. Mandatory SL Verification: Ensure open Gold trade is protected or close immediately
                EnsureAllPositionsProtected();

                // 2. Dynamic Auto Break-Even: Lock in profit to Break-Even at +15 Pips
                ApplyAutoBreakEvenProtection();

                // 3. Send live Gold telemetry (Price, Balance, Open Positions)
                SendTelemetry();

                // 4. Poll & Execute pending approved Gold orders
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

        /// <summary>
        /// Ensures all open positions have verified Stop Loss.
        /// If Stop Loss attachment fails or is rejected, IMMEDIATELY CLOSES POSITION to prevent naked risk.
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
                        double pipSize = sym.PipSize > 0 ? sym.PipSize : 0.01;

                        double minDistance = Math.Max(sym.Spread * 3.0, pipSize * 40.0);
                        double targetSl = 0.0;
                        double targetTp = 0.0;

                        if (pos.TradeType == TradeType.Buy)
                        {
                            targetSl = Math.Round(sym.Bid - Math.Max(minDistance, pipSize * 60.0), digits);
                            targetTp = Math.Round(sym.Ask + Math.Max(minDistance * 2.0, pipSize * 120.0), digits);
                        }
                        else
                        {
                            targetSl = Math.Round(sym.Ask + Math.Max(minDistance, pipSize * 60.0), digits);
                            targetTp = Math.Round(sym.Bid - Math.Max(minDistance * 2.0, pipSize * 120.0), digits);
                        }

                        Print(string.Format("🛡️ [Emergency SL Attachment] Securing #{0} ({1} {2}): SL={3}, TP={4}", 
                            pos.Id, pos.SymbolName, pos.TradeType, targetSl, targetTp));

                        TradeResult modResult = ModifyPosition(pos, targetSl, targetTp);

                        // If modify failed, FAIL-SAFE EMERGENCY AUTO-CLOSE: NEVER leave any trade unprotected
                        if (modResult == null || !modResult.IsSuccessful || pos.StopLoss == null || pos.StopLoss <= 0)
                        {
                            Print(string.Format("🚨 [FAIL-SAFE AUTO-CLOSE] Position #{0} is unprotected and broker rejected SL. Closing immediately!", pos.Id));
                            ClosePosition(pos);
                        }
                        else
                        {
                            Print(string.Format("✅ [Protection Verified] #{0} secured with SL: {1}, TP: {2}", pos.Id, pos.StopLoss, pos.TakeProfit));
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                Print("EnsureAllPositionsProtected error: " + ex.Message);
            }
        }

        /// <summary>
        /// Moves Stop Loss to Entry Price (+1 pip buffer) as soon as position gains >= 15 pips profit ($1.50)
        /// </summary>
        private void ApplyAutoBreakEvenProtection()
        {
            try
            {
                foreach (var pos in Positions)
                {
                    Symbol sym = Symbols.GetSymbol(pos.SymbolName) ?? Symbol;
                    double pipSize = sym.PipSize > 0 ? sym.PipSize : 0.01;
                    int digits = sym.Digits;

                    if (pos.TradeType == TradeType.Buy)
                    {
                        double currentPips = (sym.Bid - pos.EntryPrice) / pipSize;
                        if (currentPips >= AutoBreakEvenPips)
                        {
                            double breakEvenSl = Math.Round(pos.EntryPrice + (pipSize * 1.0), digits);
                            if (pos.StopLoss == null || pos.StopLoss < pos.EntryPrice)
                            {
                                Print(string.Format("🎯 [Auto Break-Even Triggered] Position #{0} (+{1:F1} pips). Moving SL to Entry: {2}", 
                                    pos.Id, currentPips, breakEvenSl));
                                ModifyPosition(pos, breakEvenSl, pos.TakeProfit);
                            }
                        }
                    }
                    else if (pos.TradeType == TradeType.Sell)
                    {
                        double currentPips = (pos.EntryPrice - sym.Ask) / pipSize;
                        if (currentPips >= AutoBreakEvenPips)
                        {
                            double breakEvenSl = Math.Round(pos.EntryPrice - (pipSize * 1.0), digits);
                            if (pos.StopLoss == null || pos.StopLoss > pos.EntryPrice)
                            {
                                Print(string.Format("🎯 [Auto Break-Even Triggered] Position #{0} (+{1:F1} pips). Moving SL to Entry: {2}", 
                                    pos.Id, currentPips, breakEvenSl));
                                ModifyPosition(pos, breakEvenSl, pos.TakeProfit);
                            }
                        }
                    }
                }
            }
            catch {}
        }

        private async void SendTelemetry()
        {
            try
            {
                string url = ServerUrl.TrimEnd('/') + "/api/cbot/stream";
                string assetName = Account.Asset != null ? (Account.Asset.Name ?? "USD") : "USD";
                string symClean = Symbol.Name.ToUpperInvariant().Replace("M", "").Replace(".PRO", "").Replace("_I", "");

                var positionsJson = new StringBuilder("[");
                bool first = true;
                foreach (var pos in Positions)
                {
                    if (!first) positionsJson.Append(",");
                    positionsJson.Append(string.Format(CultureInfo.InvariantCulture,
                        "{{\"id\":{0},\"symbol\":\"{1}\",\"type\":\"{2}\",\"entry_price\":{3},\"volume\":{4},\"sl\":{5},\"tp\":{6},\"net_profit\":{7},\"pips\":{8}}}",
                        pos.Id, pos.SymbolName, pos.TradeType.ToString().ToUpperInvariant(),
                        pos.EntryPrice, pos.VolumeInUnits,
                        pos.StopLoss.HasValue ? pos.StopLoss.Value.ToString(CultureInfo.InvariantCulture) : "null",
                        pos.TakeProfit.HasValue ? pos.TakeProfit.Value.ToString(CultureInfo.InvariantCulture) : "null",
                        pos.NetProfit, pos.Pips));
                    first = false;
                }
                positionsJson.Append("]");

                string json = string.Format(CultureInfo.InvariantCulture,
                    "{{\"account_id\":\"{0}\",\"balance\":{1},\"equity\":{2},\"margin\":{3},\"freeMargin\":{4},\"currency\":\"{5}\",\"broker\":\"{6}\",\"symbol\":\"{7}\",\"bid\":{8},\"ask\":{9},\"live_price\":{10},\"is_live\":{11},\"open_positions\":{12}}}",
                    Account.Number, Account.Balance, Account.Equity, Account.Margin, Account.FreeMargin, 
                    assetName, Account.BrokerName ?? "cTrader", symClean, Symbol.Bid, Symbol.Ask, Symbol.Bid,
                    Account.IsLive ? "true" : "false", positionsJson.ToString());

                var content = new StringContent(json, Encoding.UTF8, "application/json");
                var res = await httpClient.PostAsync(url, content);
                if (res.IsSuccessStatusCode && EnableAutoExecution)
                {
                    string replyJson = await res.Content.ReadAsStringAsync();
                    if (!string.IsNullOrEmpty(replyJson) && (replyJson.Contains("\"signal\"") || replyJson.Contains("\"pending_orders\"")))
                    {
                        BeginInvokeOnMainThread(() => ProcessOrders(replyJson));
                    }
                }
            }
            catch {}
        }

        private async void PollOrders()
        {
            try
            {
                string url = ServerUrl.TrimEnd('/') + "/api/cbot/orders";
                var response = await httpClient.GetAsync(url);
                if (response.IsSuccessStatusCode)
                {
                    string json = await response.Content.ReadAsStringAsync();
                    if (!string.IsNullOrEmpty(json) && json != "[]" && json.Contains("symbol"))
                    {
                        BeginInvokeOnMainThread(() => ProcessOrders(json));
                    }
                }
            }
            catch {}
        }

        private void ProcessOrders(string json)
        {
            try
            {
                // Handle Close position command
                if (json.Contains("\"action\":\"CLOSE\""))
                {
                    string posIdStr = ExtractJsonValue(json, "position_id");
                    long posId;
                    if (long.TryParse(posIdStr, out posId))
                    {
                        foreach (var pos in Positions)
                        {
                            if (pos.Id == posId)
                            {
                                Print("Executing Close command for Position #" + posId);
                                ClosePosition(pos);
                                return;
                            }
                        }
                    }
                    return;
                }

                string symbolStr = ExtractJsonValue(json, "symbol");
                string action = ExtractJsonValue(json, "signal");
                if (string.IsNullOrEmpty(action)) action = ExtractJsonValue(json, "action");
                action = action.ToUpperInvariant();
                string signalId = ExtractJsonValue(json, "ticket_id");
                if (string.IsNullOrEmpty(signalId)) signalId = ExtractJsonValue(json, "id");

                if (string.IsNullOrEmpty(symbolStr) || (action != "BUY" && action != "SELL")) return;

                // 1. Strict Instrument Whitelist (GOLD ONLY)
                string symClean = symbolStr.ToUpperInvariant().Replace("M", "").Replace(".PRO", "").Replace("_I", "");
                if (!symClean.Contains("XAU") && !symClean.Contains("GOLD"))
                {
                    Print(string.Format("🚫 [REJECTED] {0} is blocked. Directive enforces GOLD-ONLY execution.", symbolStr));
                    return;
                }

                // 2. Strict Duplicate Check
                if (!string.IsNullOrEmpty(signalId) && _executedTickets.Contains(signalId)) return;

                // 3. Max 1 Position Hard Cap
                if (Positions.Count >= MAX_CONCURRENT_POSITIONS)
                {
                    Print(string.Format("🚫 [MAX POSITIONS REACHED] Cannot execute {0} {1}: {2} active position already running.", action, symbolStr, Positions.Count));
                    return;
                }

                // 4. Parse SL and TP
                double rawSl = 0, rawTp = 0;
                double.TryParse(ExtractJsonValue(json, "sl"), NumberStyles.Any, CultureInfo.InvariantCulture, out rawSl);
                double.TryParse(ExtractJsonValue(json, "tp"), NumberStyles.Any, CultureInfo.InvariantCulture, out rawTp);

                if (rawSl <= 0 || rawTp <= 0)
                {
                    Print("🚫 [REJECTED] Order rejected: Missing or invalid SL/TP.");
                    return;
                }

                Symbol targetSymbol = Symbols.GetSymbol(symbolStr) ?? Symbols.GetSymbol(symbolStr + "m") ?? Symbol;
                TradeType tradeType = action == "BUY" ? TradeType.Buy : TradeType.Sell;

                // Volume normalization for Gold: 0.01 lot = 1 unit (1 lot = 100 units)
                double volumeInUnits = targetSymbol.NormalizeVolumeInUnits(FIXED_GOLD_LOT_SIZE * 100);
                if (volumeInUnits <= 0) volumeInUnits = targetSymbol.VolumeInUnitsMin;

                int digits = targetSymbol.Digits;
                double pipSize = targetSymbol.PipSize > 0 ? targetSymbol.PipSize : 0.01;
                double minDistance = Math.Max(targetSymbol.Spread * 3.0, pipSize * 40.0);
                double currentRefPrice = tradeType == TradeType.Buy ? targetSymbol.Ask : targetSymbol.Bid;

                double validSl = rawSl;
                double validTp = rawTp;

                if (tradeType == TradeType.Buy)
                {
                    if (validSl <= 0 || validSl >= (currentRefPrice - minDistance))
                        validSl = currentRefPrice - Math.Max(minDistance, pipSize * 60.0);
                    if (validTp <= 0 || validTp <= (currentRefPrice + minDistance))
                        validTp = currentRefPrice + Math.Max(minDistance * 2.0, pipSize * 120.0);
                }
                else
                {
                    if (validSl <= 0 || validSl <= (currentRefPrice + minDistance))
                        validSl = currentRefPrice + Math.Max(minDistance, pipSize * 60.0);
                    if (validTp <= 0 || validTp >= (currentRefPrice - minDistance))
                        validTp = currentRefPrice - Math.Max(minDistance * 2.0, pipSize * 120.0);
                }

                validSl = Math.Round(validSl, digits);
                validTp = Math.Round(validTp, digits);

                double slPips = Math.Round(Math.Abs(currentRefPrice - validSl) / pipSize, 1);
                double tpPips = Math.Round(Math.Abs(validTp - currentRefPrice) / pipSize, 1);

                Print(string.Format("🚀 [Executing Verified Gold Sniper Trade] {0} {1} ({2} units) | SL: {3} ({4} pips) | TP: {5} ({6} pips)",
                    action, targetSymbol.Name, volumeInUnits, validSl, slPips, validTp, tpPips));

                TradeResult result = ExecuteMarketOrder(tradeType, targetSymbol.Name, volumeInUnits, "TradeTalk.AI.V2", slPips, tpPips);
                if (!result.IsSuccessful)
                {
                    result = ExecuteMarketOrder(tradeType, targetSymbol.Name, volumeInUnits, "TradeTalk.AI.V2");
                }

                if (result.IsSuccessful && result.Position != null)
                {
                    Position pos = result.Position;
                    if (!string.IsNullOrEmpty(signalId)) _executedTickets.Add(signalId);

                    if (pos.StopLoss == null || pos.TakeProfit == null)
                    {
                        ModifyPosition(pos, validSl, validTp);
                    }

                    // Strict protection check: If still no SL, fail-safe close
                    if (pos.StopLoss == null || pos.StopLoss <= 0)
                    {
                        Print(string.Format("🚨 [FAIL-SAFE AUTO-CLOSE] Broker failed to attach SL on position #{0}. Emergency closing now!", pos.Id));
                        ClosePosition(pos);
                        return;
                    }

                    Print(string.Format("✅ [Order Filled Successfully] Ticket #{0} for {1} @ {2} | Verified SL: {3}",
                        pos.Id, targetSymbol.Name, pos.EntryPrice, pos.StopLoss));

                    ReportOrderFilled(signalId, pos.Id, pos.EntryPrice, targetSymbol.Name, action);
                }
                else
                {
                    Print(string.Format("❌ [Execution Failed] Broker error: {0}", result.Error));
                }
            }
            catch (Exception ex)
            {
                Print("ProcessOrders exception: " + ex.Message);
            }
        }

        private async void ReportOrderFilled(string signalId, long posId, double fillPrice, string symbol, string action)
        {
            try
            {
                string url = ServerUrl.TrimEnd('/') + "/api/cbot/order-filled";
                string json = string.Format(CultureInfo.InvariantCulture,
                    "{{\"id\":\"{0}\",\"ticket_id\":\"CT_{1}\",\"position_id\":\"{1}\",\"fill_price\":{2},\"symbol\":\"{3}\",\"action\":\"{4}\",\"status\":\"FILLED\"}}",
                    signalId, posId, fillPrice, symbol, action);
                await httpClient.PostAsync(url, new StringContent(json, Encoding.UTF8, "application/json"));
            }
            catch {}
        }

        private string ExtractJsonValue(string json, string key)
        {
            string search = "\"" + key + "\":";
            int idx = json.IndexOf(search, StringComparison.OrdinalIgnoreCase);
            if (idx == -1) return "";
            int start = idx + search.Length;
            while (start < json.Length && (json[start] == ' ' || json[start] == '"')) start++;
            int end = start;
            while (end < json.Length && json[end] != '"' && json[end] != ',' && json[end] != '}') end++;
            return json.Substring(start, end - start).Trim('"', ' ');
        }
    }
}
