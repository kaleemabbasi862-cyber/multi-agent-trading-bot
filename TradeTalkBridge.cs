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

            Print("=================================================");
            Print("TradeTalk.AI Autonomous Trading & Protection Bridge Started");
            Print("Account Number: " + Account.Number);
            Print("Live Balance: " + Account.Balance + " " + assetName);
            Print("Target Server: " + ServerUrl);
            Print("Sniper Auto Break-Even Guard: +" + AutoBreakEvenPips + " Pips");
            Print("=================================================");

            EnsureAllPositionsProtected();
            SendTelemetry();
            Timer.Start(SyncInterval);
        }

        protected override void OnTimer()
        {
            try
            {
                // 1. Post-Execution & Open Trade Guard: Ensure every open position has valid SL and TP
                EnsureAllPositionsProtected();

                // 2. Dynamic Auto-Protection: Lock in profit to Break-Even at +15 Pips
                ApplyAutoBreakEvenProtection();

                // 3. Send live telemetry (Balance, Equity, Live Prices, Open Positions)
                SendTelemetry();

                // 4. Poll & Execute pending approved orders
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
        /// Scans all open positions and attaches safe SL and TP if currently unprotected (-- / --).
        /// Caches failed modification attempts until price moves by at least 30 pips.
        /// Strictly enforces (Spread * 3.0) minimum distance from current market price.
        /// </summary>
        private void EnsureAllPositionsProtected()
        {
            try
            {
                foreach (var pos in Positions)
                {
                    if (pos.StopLoss == null || pos.TakeProfit == null)
                    {
                        Symbol sym = Symbols.GetSymbol(pos.SymbolName) ?? Symbol;
                        int digits = sym.Digits;
                        double pipSize = sym.PipSize > 0 ? sym.PipSize : Math.Pow(10, -digits);
                        if (pos.SymbolName.Contains("XAG") || pos.SymbolName.Contains("SILVER"))
                        {
                            pipSize = Math.Pow(10, -digits);
                        }

                        double currentMarketPrice = (pos.TradeType == TradeType.Buy) ? sym.Bid : sym.Ask;

                        // 1. Cache failed modification check: require at least 30 pips movement before retrying
                        if (_failedModifications.ContainsKey(pos.Id))
                        {
                            double lastAttemptPrice = _failedModifications[pos.Id];
                            double movedPips = Math.Abs(currentMarketPrice - lastAttemptPrice) / pipSize;
                            if (movedPips < 30.0)
                            {
                                continue; // Skip to prevent repetitive popups
                            }
                        }

                        // 2. Dynamic Stop Loss Distance: strictly at least (Spread * 3.0) and at least 30 pips away
                        double minRequiredDistance = Math.Max(sym.Spread * 3.0, pipSize * 30.0);

                        double? targetSl = pos.StopLoss;
                        double? targetTp = pos.TakeProfit;

                        if (pos.TradeType == TradeType.Buy)
                        {
                            // SL for BUY must be strictly BELOW current Bid
                            if (targetSl == null || targetSl >= (sym.Bid - minRequiredDistance))
                            {
                                targetSl = Math.Round(sym.Bid - Math.Max(minRequiredDistance, pipSize * 60.0), digits);
                            }

                            // TP for BUY must be strictly ABOVE current Ask
                            if (targetTp == null || targetTp <= (sym.Ask + minRequiredDistance))
                            {
                                targetTp = Math.Round(sym.Ask + Math.Max(minRequiredDistance * 2.0, pipSize * 120.0), digits);
                            }

                            // Strict validation check: SL strictly below Bid - (Spread * 3)
                            if (targetSl >= (sym.Bid - (sym.Spread * 3.0)))
                            {
                                continue;
                            }
                        }
                        else // SELL
                        {
                            // SL for SELL must be strictly ABOVE current Ask
                            if (targetSl == null || targetSl <= (sym.Ask + minRequiredDistance))
                            {
                                targetSl = Math.Round(sym.Ask + Math.Max(minRequiredDistance, pipSize * 60.0), digits);
                            }

                            // TP for SELL must be strictly BELOW current Bid
                            if (targetTp == null || targetTp >= (sym.Bid - minRequiredDistance))
                            {
                                targetTp = Math.Round(sym.Bid - Math.Max(minRequiredDistance * 2.0, pipSize * 120.0), digits);
                            }

                            // Strict validation check: SL strictly above Ask + (Spread * 3)
                            if (targetSl <= (sym.Ask + (sym.Spread * 3.0)))
                            {
                                continue;
                            }
                        }

                        Print(string.Format("🛡️ [Auto-Protection Guard] Modifying #{0} ({1} {2}): Current={3}, SL={4}, TP={5}", 
                            pos.Id, pos.SymbolName, pos.TradeType, currentMarketPrice, targetSl, targetTp));

                        TradeResult modResult = ModifyPosition(pos, targetSl, targetTp);
                        if (modResult != null && !modResult.IsSuccessful)
                        {
                            Print(string.Format("⚠️ ModifyPosition for #{0} rejected: {1}. Caching attempt until 30 pips movement.", pos.Id, modResult.Error));
                            _failedModifications[pos.Id] = currentMarketPrice;
                        }
                        else
                        {
                            if (_failedModifications.ContainsKey(pos.Id))
                            {
                                _failedModifications.Remove(pos.Id);
                            }
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                Print("Position protection guard note: " + ex.Message);
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
                            // Ensure break even is strictly below current Bid - (Spread * 3)
                            if (targetBe < (posSym.Bid - (posSym.Spread * 3.0)))
                            {
                                if (pos.StopLoss == null || pos.StopLoss < pos.EntryPrice)
                                {
                                    Print(string.Format("🛡️ [Auto Break-Even] Locking Profit for #{0} ({1} +{2:F1} Pips)! Moving SL to Break-Even @ {3:F5}", pos.Id, pos.SymbolName, pos.Pips, targetBe));
                                    ModifyPosition(pos, targetBe, pos.TakeProfit);
                                }
                            }
                        }
                        else if (pos.TradeType == TradeType.Sell)
                        {
                            double targetBe = Math.Round(pos.EntryPrice - (1.0 * pipSize), posSym.Digits);
                            // Ensure break even is strictly above current Ask + (Spread * 3)
                            if (targetBe > (posSym.Ask + (posSym.Spread * 3.0)))
                            {
                                if (pos.StopLoss == null || pos.StopLoss > pos.EntryPrice)
                                {
                                    Print(string.Format("🛡️ [Auto Break-Even] Locking Profit for #{0} ({1} +{2:F1} Pips)! Moving SL to Break-Even @ {3:F5}", pos.Id, pos.SymbolName, pos.Pips, targetBe));
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
                string broker = Account.BrokerName ?? "IC Markets cTrader Live";

                string symClean = Symbol.Name.Replace("m", "").Replace(".pro", "").Replace("_i", "").ToUpperInvariant();

                // Serialize Active Open Positions
                StringBuilder positionsJson = new StringBuilder("[");
                int count = 0;
                foreach (var pos in Positions)
                {
                    if (count > 0) positionsJson.Append(",");
                    
                    bool isBeActive = false;
                    if (pos.StopLoss != null)
                    {
                        if (pos.TradeType == TradeType.Buy && pos.StopLoss >= pos.EntryPrice) isBeActive = true;
                        if (pos.TradeType == TradeType.Sell && pos.StopLoss <= pos.EntryPrice) isBeActive = true;
                    }

                    positionsJson.Append(string.Format(
                        CultureInfo.InvariantCulture,
                        "{{\"id\":{0},\"symbol\":\"{1}\",\"trade_type\":\"{2}\",\"volume\":{3},\"entry_price\":{4},\"net_profit\":{5},\"pips\":{6},\"sl\":{7},\"tp\":{8},\"be_active\":{9}}}",
                        pos.Id,
                        pos.SymbolName,
                        pos.TradeType,
                        pos.VolumeInUnits,
                        pos.EntryPrice,
                        pos.NetProfit,
                        pos.Pips,
                        pos.StopLoss ?? 0,
                        pos.TakeProfit ?? 0,
                        isBeActive ? "true" : "false"
                    ));
                    count++;
                }
                positionsJson.Append("]");

                string jsonPayload = string.Format(
                    CultureInfo.InvariantCulture,
                    "{{\"account_id\":\"{0}\",\"accountNumber\":\"{0}\",\"balance\":{1},\"equity\":{2},\"margin\":{3},\"freeMargin\":{4},\"currency\":\"{5}\",\"broker\":\"{6}\",\"symbol\":\"{7}\",\"bid\":{8},\"ask\":{9},\"live_price\":{8},\"open_positions\":{10}}}",
                    Account.Number,
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
                            Print("🚨 [TradeTalk Dashboard Command] Closing Position #" + posId + " with Net Profit: $" + pos.NetProfit);
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

                double lotSize = 0.01;
                double.TryParse(ExtractJsonValue(json, "lots"), NumberStyles.Any, CultureInfo.InvariantCulture, out lotSize);
                if (lotSize <= 0) double.TryParse(ExtractJsonValue(json, "lot_size"), NumberStyles.Any, CultureInfo.InvariantCulture, out lotSize);
                if (lotSize <= 0) lotSize = 0.01;

                double rawSl = 0;
                double.TryParse(ExtractJsonValue(json, "sl"), NumberStyles.Any, CultureInfo.InvariantCulture, out rawSl);

                double rawTp = 0;
                double.TryParse(ExtractJsonValue(json, "tp"), NumberStyles.Any, CultureInfo.InvariantCulture, out rawTp);

                Symbol targetSymbol = ResolveBrokerSymbol(symbolStr);
                if (targetSymbol == null)
                {
                    Print("❌ Error: Broker symbol not found for " + symbolStr);
                    return;
                }

                TradeType tradeType = (action == "BUY") ? TradeType.Buy : TradeType.Sell;

                double volumeInUnits = targetSymbol.NormalizeVolumeInUnits(lotSize * 100000);
                if (targetSymbol.Name.Contains("XAU") || targetSymbol.Name.Contains("GOLD"))
                {
                    volumeInUnits = targetSymbol.NormalizeVolumeInUnits(lotSize * 100);
                }
                else if (targetSymbol.Name.Contains("XAG") || targetSymbol.Name.Contains("SILVER"))
                {
                    volumeInUnits = targetSymbol.NormalizeVolumeInUnits(lotSize * 1000);
                }

                // 1. Commodity & Metal Precision Pip Size Normalization
                int digits = targetSymbol.Digits;
                double pipSize = targetSymbol.PipSize > 0 ? targetSymbol.PipSize : Math.Pow(10, -digits);
                if (targetSymbol.Name.Contains("XAG") || targetSymbol.Name.Contains("SILVER"))
                {
                    pipSize = Math.Pow(10, -digits);
                }

                // 2. Dynamic Stop-Level Enforcement (Strictly at least Spread * 3.0 and at least 30 pips)
                double minDistance = Math.Max(targetSymbol.Spread * 3.0, pipSize * 30.0);

                double currentRefPrice = (tradeType == TradeType.Buy) ? targetSymbol.Ask : targetSymbol.Bid;
                double validSl = rawSl;
                double validTp = rawTp;

                if (tradeType == TradeType.Buy)
                {
                    if (validSl <= 0 || validSl >= (targetSymbol.Bid - minDistance))
                    {
                        validSl = targetSymbol.Bid - Math.Max(minDistance, pipSize * 60.0);
                    }
                    if (validTp <= 0 || validTp <= (targetSymbol.Ask + minDistance))
                    {
                        validTp = targetSymbol.Ask + Math.Max(minDistance * 2.0, pipSize * 120.0);
                    }
                }
                else
                {
                    if (validSl <= 0 || validSl <= (targetSymbol.Ask + minDistance))
                    {
                        validSl = targetSymbol.Ask + Math.Max(minDistance, pipSize * 60.0);
                    }
                    if (validTp <= 0 || validTp >= (targetSymbol.Bid - minDistance))
                    {
                        validTp = targetSymbol.Bid - Math.Max(minDistance * 2.0, pipSize * 120.0);
                    }
                }

                validSl = Math.Round(validSl, digits);
                validTp = Math.Round(validTp, digits);

                double slPips = Math.Round(Math.Abs(currentRefPrice - validSl) / pipSize, 1);
                double tpPips = Math.Round(Math.Abs(validTp - currentRefPrice) / pipSize, 1);

                Print(string.Format("🎯 [Dynamic Protection Execution] Dispatching {0} {1} ({2} Units | SL: {3} ({4} Pips) | TP: {5} ({6} Pips))...", 
                    action, targetSymbol.Name, volumeInUnits, validSl, slPips, validTp, tpPips));

                // 3. Attempt market execution with embedded SL/TP pips
                TradeResult result = ExecuteMarketOrder(tradeType, targetSymbol.Name, volumeInUnits, "TradeTalk.AI", slPips, tpPips);
                
                // 4. Auto-Recovery Fallback: If broker rejects embedded SL/TP, execute clean market order and modify immediately
                if (!result.IsSuccessful)
                {
                    Print("⚠️ Embedded SL/TP rejected by broker (" + result.Error + ") -> Instant clean Market Order fallback...");
                    result = ExecuteMarketOrder(tradeType, targetSymbol.Name, volumeInUnits, "TradeTalk.AI");
                }

                if (result.IsSuccessful && result.Position != null)
                {
                    Position pos = result.Position;
                    if (!string.IsNullOrEmpty(signalId)) _executedTickets.Add(signalId);

                    Print(string.Format("🟢 cTrader Order FILLED! Position ID: #{0} | Entry: {1} | Initial SL: {2} | Initial TP: {3}", 
                        pos.Id, pos.EntryPrice, pos.StopLoss, pos.TakeProfit));

                    // 5. Fallback Post-Execution Protection: Ensure SL and TP are 100% attached
                    if (pos.StopLoss == null || pos.TakeProfit == null)
                    {
                        try 
                        { 
                            Print(string.Format("🛡️ Attaching guaranteed protection to #{0}: SL={1}, TP={2}", pos.Id, validSl, validTp));
                            TradeResult modRes = ModifyPosition(pos, validSl, validTp); 
                            if (modRes != null && !modRes.IsSuccessful)
                            {
                                _failedModifications[pos.Id] = currentRefPrice;
                            }
                        } 
                        catch (Exception modEx)
                        {
                            Print("Secondary ModifyPosition note: " + modEx.Message);
                            _failedModifications[pos.Id] = currentRefPrice;
                        }
                    }

                    // 6. Notify TradeTalk server with authentic cTrader Position ID
                    ReportOrderFilled(signalId, pos.Id, pos.EntryPrice, targetSymbol.Name, action);
                }
                else
                {
                    Print("🔴 cTrader Execution Failed: " + result.Error);
                }
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
