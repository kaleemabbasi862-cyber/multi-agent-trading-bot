using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Net;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using cAlgo.API;
using cAlgo.API.Internals;

namespace cAlgo.Robots
{
    [Robot(TimeZone = TimeZones.UTC, AccessRights = AccessRights.FullAccess)]
    public class TradeTalkBridge : Robot
    {
        [Parameter("HTTP Port", DefaultValue = 5001, MinValue = 1024, MaxValue = 65535)]
        public int Port { get; set; }

        [Parameter("Max Concurrent Positions", DefaultValue = 1, MinValue = 1, MaxValue = 5)]
        public int MaxConcurrentPositions { get; set; }

        [Parameter("Min SL Dollars on Gold (e.g. 3.50 = $3.50)", DefaultValue = 3.50, MinValue = 1.0, MaxValue = 50.0)]
        public double MinStopLossDollarsGold { get; set; }

        [Parameter("Min Hold Time Seconds", DefaultValue = 300, MinValue = 0, MaxValue = 3600)]
        public int MinHoldTimeSeconds { get; set; }

        private HttpListener _listener;
        private CancellationTokenSource _cts;
        private Thread _listenerThread;
        private readonly object _orderLock = new object();

        protected override void OnStart()
        {
            _cts = new CancellationTokenSource();
            StartHttpServer();

            Print("======================================================================");
            Print("   TRADETALK PRODUCTION C# BRIDGE (CleanBridge v2.1)                 ");
            Print("======================================================================");
            Print(string.Format("Account: #{0} ({1}) | Broker: {2}", Account.Number, Account.IsLive ? "LIVE" : "DEMO", Account.BrokerName));
            Print(string.Format(CultureInfo.InvariantCulture, "Balance: ${0:F2} | Equity: ${1:F2}", Account.Balance, Account.Equity));
            Print(string.Format("Listening on: http://127.0.0.1:{0}/", Port));
            Print(string.Format("Guards: Max Pos = {0} | Min Gold SL = ${1:F2} | Min Hold = {2}s", MaxConcurrentPositions, MinStopLossDollarsGold, MinHoldTimeSeconds));
            Print("Automated Tick Modifications / Trailing Stops: COMPLETELY DISABLED");
            Print("======================================================================");
        }

        // ABSOLUTELY NO OnTick() or automated tick modifications to prevent premature spread stops

        private void StartHttpServer()
        {
            try
            {
                _listener = new HttpListener();
                string prefixIp = string.Format("http://127.0.0.1:{0}/", Port);
                string prefixLocalhost = string.Format("http://localhost:{0}/", Port);

                _listener.Prefixes.Add(prefixIp);
                try
                {
                    _listener.Prefixes.Add(prefixLocalhost);
                }
                catch { }

                _listener.Start();

                _listenerThread = new Thread(ListenLoop)
                {
                    IsBackground = true,
                    Name = "TradeTalkBridgeListener"
                };
                _listenerThread.Start();
                Print(string.Format("🟢 HTTP Bridge Active on {0}", prefixIp));
            }
            catch (Exception ex)
            {
                Print("🚨 Failed to start HTTP Bridge server: " + ex.Message);
            }
        }

        private void ListenLoop()
        {
            while (_listener != null && _listener.IsListening && !_cts.Token.IsCancellationRequested)
            {
                try
                {
                    var context = _listener.GetContext();
                    ThreadPool.QueueUserWorkItem(ProcessRequest, context);
                }
                catch (HttpListenerException)
                {
                    break;
                }
                catch (Exception ex)
                {
                    Print("Listener loop warning: " + ex.Message);
                }
            }
        }

        private T RunOnMainThread<T>(Func<T> func)
        {
            var tcs = new TaskCompletionSource<T>();
            try
            {
                BeginInvokeOnMainThread(() =>
                {
                    try
                    {
                        var result = func();
                        tcs.TrySetResult(result);
                    }
                    catch (Exception ex)
                    {
                        Print("🚨 Error in MainThread delegate: " + ex.ToString());
                        tcs.TrySetException(ex);
                    }
                });
            }
            catch (Exception ex)
            {
                Print("🚨 Error dispatching to MainThread: " + ex.ToString());
                tcs.TrySetException(ex);
            }

            if (tcs.Task.Wait(TimeSpan.FromSeconds(5)))
            {
                return tcs.Task.Result;
            }
            else
            {
                throw new TimeoutException("cTrader main thread did not respond within 5 seconds.");
            }
        }

        private void ProcessRequest(object state)
        {
            var context = (HttpListenerContext)state;
            var request = context.Request;
            var response = context.Response;

            // CORS Headers
            response.Headers.Add("Access-Control-Allow-Origin", "*");
            response.Headers.Add("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
            response.Headers.Add("Access-Control-Allow-Headers", "Content-Type, Authorization");
            response.ContentType = "application/json";

            try
            {
                if (request.HttpMethod == "OPTIONS")
                {
                    response.StatusCode = 200;
                    SendJsonResponse(response, "{\"status\": \"OK\"}");
                    return;
                }

                string rawPath = (request.Url != null && !string.IsNullOrEmpty(request.Url.AbsolutePath)) 
                    ? request.Url.AbsolutePath.ToLowerInvariant().TrimEnd('/') 
                    : "";

                if (request.HttpMethod == "GET")
                {
                    if (rawPath == "/positions" || rawPath == "/trade/positions")
                    {
                        string posJson = RunOnMainThread(GetPositionsJson);
                        response.StatusCode = 200;
                        SendJsonResponse(response, posJson);
                        return;
                    }
                    else if (rawPath == "/history" || rawPath == "/trade/history")
                    {
                        string histJson = RunOnMainThread(GetHistoryJson);
                        response.StatusCode = 200;
                        SendJsonResponse(response, histJson);
                        return;
                    }
                    else
                    {
                        string statusJson = RunOnMainThread(GetOverviewJson);
                        response.StatusCode = 200;
                        SendJsonResponse(response, statusJson);
                        return;
                    }
                }

                if (request.HttpMethod == "POST")
                {
                    string requestBody;
                    using (var reader = new StreamReader(request.InputStream, request.ContentEncoding ?? Encoding.UTF8))
                    {
                        requestBody = reader.ReadToEnd();
                    }

                    Print("📥 Inbound Bridge Request: " + requestBody);

                    var executionResult = RunOnMainThread(() =>
                    {
                        int httpStatus;
                        string resultJson = HandleTradeExecution(requestBody, out httpStatus);
                        return new Tuple<int, string>(httpStatus, resultJson);
                    });

                    response.StatusCode = executionResult.Item1;
                    SendJsonResponse(response, executionResult.Item2);
                    return;
                }

                response.StatusCode = 405;
                SendJsonResponse(response, "{\"status\":\"ERROR\",\"message\":\"Method Not Allowed\"}");
            }
            catch (Exception ex)
            {
                Print("Request processing error: " + ex.Message);
                response.StatusCode = 500;
                SendJsonResponse(response, string.Format("{{\"status\":\"ERROR\",\"message\":\"{0}\"}}", EscapeJson(ex.Message)));
            }
        }

        private string GetPositionsJson()
        {
            var posList = new List<string>();
            if (Positions != null)
            {
                foreach (var p in Positions)
                {
                    if (p == null) continue;
                    Symbol sym = Symbols.GetSymbol(p.SymbolName);
                    double lots = sym != null ? sym.VolumeInUnitsToQuantity(p.VolumeInUnits) : (p.VolumeInUnits / 100000.0);
                    
                    posList.Add(string.Format(CultureInfo.InvariantCulture,
                        "{{\"id\":{0},\"symbol\":\"{1}\",\"trade_type\":\"{2}\",\"volume\":{3:F2},\"volume_units\":{4},\"entry_price\":{5},\"sl\":{6},\"tp\":{7},\"net_profit\":{8:F2},\"pips\":{9:F1},\"entry_time\":\"{10:O}\",\"comment\":\"{11}\"}}",
                        p.Id, p.SymbolName ?? "", p.TradeType.ToString().ToUpperInvariant(), lots, p.VolumeInUnits, p.EntryPrice, p.StopLoss ?? 0, p.TakeProfit ?? 0, p.NetProfit, p.Pips, p.EntryTime, EscapeJson(p.Comment ?? "")));
                }
            }
            return "[" + string.Join(",", posList) + "]";
        }

        private string GetHistoryJson()
        {
            var histList = new List<string>();
            if (History != null)
            {
                int maxHist = 50;
                int count = 0;
                for (int i = History.Count - 1; i >= 0 && count < maxHist; i--)
                {
                    var h = History[i];
                    if (h == null) continue;
                    Symbol sym = Symbols.GetSymbol(h.SymbolName);
                    double lots = sym != null ? sym.VolumeInUnitsToQuantity(h.VolumeInUnits) : (h.VolumeInUnits / 100000.0);

                    histList.Add(string.Format(CultureInfo.InvariantCulture,
                        "{{\"id\":{0},\"position_id\":{0},\"symbol\":\"{1}\",\"trade_type\":\"{2}\",\"volume\":{3:F2},\"entry_price\":{4},\"closing_price\":{5},\"net_profit\":{6:F2},\"pips\":{7:F1},\"closing_time\":\"{8:O}\",\"entry_time\":\"{9:O}\",\"comment\":\"{10}\"}}",
                        h.PositionId, h.SymbolName ?? "", h.TradeType.ToString().ToUpperInvariant(), lots, h.EntryPrice, h.ClosingPrice, h.NetProfit, h.Pips, h.ClosingTime, h.EntryTime, EscapeJson(h.Comment ?? "")));
                    count++;
                }
            }
            return "[" + string.Join(",", histList) + "]";
        }

        private string GetOverviewJson()
        {
            string posJson = GetPositionsJson();
            string histJson = GetHistoryJson();

            string accNum = Account != null ? Account.Number.ToString() : "0";
            string broker = Account != null ? Account.BrokerName : "cTrader";
            bool isLive = Account != null && Account.IsLive;
            double bal = Account != null ? Account.Balance : 0.0;
            double eq = Account != null ? Account.Equity : 0.0;
            double marg = Account != null ? Account.Margin : 0.0;
            double freeMarg = Account != null ? Account.FreeMargin : 0.0;
            int openCount = Positions != null ? Positions.Count : 0;

            return string.Format(CultureInfo.InvariantCulture,
                "{{\"status\":\"ONLINE\",\"bridge\":\"TradeTalk CleanBridge C#\",\"account_id\":\"{0}\",\"broker\":\"{1}\",\"is_live\":{2},\"balance\":{3:F2},\"equity\":{4:F2},\"margin\":{5:F2},\"free_margin\":{6:F2},\"open_positions_count\":{7},\"positions\":{8},\"history\":{9}}}",
                accNum, broker, isLive ? "true" : "false", bal, eq, marg, freeMarg, openCount, posJson, histJson);
        }

        private string HandleTradeExecution(string json, out int httpStatus)
        {
            lock (_orderLock)
            {
                try
                {
                    string actionStr = (ExtractJsonValue(json, "action") ?? ExtractJsonValue(json, "side") ?? ExtractJsonValue(json, "trade_type") ?? "BUY").ToUpperInvariant();
                    string symbolStr = ExtractJsonValue(json, "symbol") ?? "XAUUSD";
                    string comment = ExtractJsonValue(json, "comment") ?? "CleanBridge AI";

                    // 1. Close Position Handler with STRICT Anti-Churn 300s Hold Guard
                    if (actionStr == "CLOSE" || actionStr.Contains("CLOSE"))
                    {
                        string targetPosId = ExtractJsonValue(json, "position_id") ?? ExtractJsonValue(json, "id");
                        string forceStr = ExtractJsonValue(json, "force") ?? "false";
                        bool isForce = forceStr.ToLowerInvariant() == "true";

                        Position targetPos = null;
                        if (Positions != null)
                        {
                            foreach (var p in Positions)
                            {
                                if (string.IsNullOrEmpty(targetPosId) || p.Id.ToString() == targetPosId)
                                {
                                    targetPos = p;
                                    break;
                                }
                            }
                        }

                        if (targetPos != null)
                        {
                            double openDurationSec = (Server.TimeInUtc - targetPos.EntryTime).TotalSeconds;
                            if (openDurationSec < MinHoldTimeSeconds && !isForce)
                            {
                                Print(string.Format("⏳ [ANTI-CHURN HOLD GUARD] Rejected Close for #{0}. Open for {1:F0}s (< {2}s min hold time).", targetPos.Id, openDurationSec, MinHoldTimeSeconds));
                                httpStatus = 400;
                                return string.Format(CultureInfo.InvariantCulture,
                                    "{{\"status\":\"REJECTED\",\"error\":\"MINIMUM_HOLD_TIME_NOT_MET\",\"message\":\"Trade open for {0:F0}s / {1}s.\",\"position_id\":{2}}}",
                                    openDurationSec, MinHoldTimeSeconds, targetPos.Id);
                            }

                            var closeResult = ClosePosition(targetPos);
                            Print(string.Format("🛑 [POSITION CLOSED] #{0} ({1}) Net Profit: ${2:F2}", targetPos.Id, targetPos.SymbolName, targetPos.NetProfit));
                            httpStatus = 200;
                            return string.Format(CultureInfo.InvariantCulture,
                                "{{\"status\":\"SUCCESS\",\"message\":\"Position #{0} closed.\",\"position_id\":{0}}}", targetPos.Id);
                        }

                        httpStatus = 404;
                        return "{\"status\":\"ERROR\",\"error\":\"POSITION_NOT_FOUND\"}";
                    }

                    // 2. HARD-CODED SAFETY GUARD: MAX CONCURRENT POSITIONS = 1
                    int currentOpen = Positions != null ? Positions.Count : 0;
                    if (currentOpen >= MaxConcurrentPositions)
                    {
                        Print(string.Format("🚨 ORDER_REJECTED_MAX_POSITIONS_ACTIVE: Current open positions ({0}) >= Limit ({1})", currentOpen, MaxConcurrentPositions));
                        httpStatus = 400;
                        return string.Format(CultureInfo.InvariantCulture,
                            "{{\"status\":\"REJECTED\",\"error\":\"ORDER_REJECTED_MAX_POSITIONS_ACTIVE\",\"open_positions\":{0},\"limit\":{1}}}",
                            currentOpen, MaxConcurrentPositions);
                    }

                    // 3. Resolve Symbol
                    Symbol sym = ResolveSymbol(symbolStr);
                    if (sym == null)
                    {
                        Print("🚨 Symbol resolution failed for: " + symbolStr);
                        httpStatus = 400;
                        return string.Format("{{\"status\":\"REJECTED\",\"error\":\"SYMBOL_NOT_FOUND\",\"symbol\":\"{0}\"}}", EscapeJson(symbolStr));
                    }

                    // Spread Guard for Gold
                    bool isGold = sym.Name.ToUpperInvariant().Contains("XAU") || sym.Name.ToUpperInvariant().Contains("GOLD");
                    double spreadPrice = Math.Round(sym.Ask - sym.Bid, sym.Digits);
                    if (isGold && spreadPrice > 0.45)
                    {
                        Print(string.Format("🚨 [SPREAD GUARD] Order Vetoed: Gold spread is ${0:F2} (> $0.45 threshold).", spreadPrice));
                        httpStatus = 400;
                        return string.Format(CultureInfo.InvariantCulture,
                            "{{\"status\":\"REJECTED\",\"error\":\"EXCESSIVE_SPREAD\",\"spread\":{0:F2}}}", spreadPrice);
                    }

                    // 4. Volume parsing
                    double volumeLots = 0.01;
                    string volStr = ExtractJsonValue(json, "volume") ?? ExtractJsonValue(json, "lots") ?? ExtractJsonValue(json, "lot_size");
                    if (!string.IsNullOrEmpty(volStr))
                    {
                        double.TryParse(volStr, NumberStyles.Any, CultureInfo.InvariantCulture, out volumeLots);
                    }
                    if (volumeLots <= 0) volumeLots = 0.01;

                    double volumeInUnits = sym.QuantityToVolumeInUnits(volumeLots);

                    // 5. ACCURATE PRICE-BASED SL & TP CALCULATION FOR GOLD & FOREX
                    double pipSize = sym.PipSize > 0 ? sym.PipSize : 0.01;
                    TradeType tradeType = actionStr.Contains("BUY") ? TradeType.Buy : TradeType.Sell;

                    // Parse inputs
                    double inSlPips = 0;
                    double inTpPips = 0;
                    string slPipsStr = ExtractJsonValue(json, "sl_pips") ?? ExtractJsonValue(json, "stop_loss_pips");
                    string tpPipsStr = ExtractJsonValue(json, "tp_pips") ?? ExtractJsonValue(json, "take_profit_pips");
                    if (!string.IsNullOrEmpty(slPipsStr)) double.TryParse(slPipsStr, NumberStyles.Any, CultureInfo.InvariantCulture, out inSlPips);
                    if (!string.IsNullOrEmpty(tpPipsStr)) double.TryParse(tpPipsStr, NumberStyles.Any, CultureInfo.InvariantCulture, out inTpPips);

                    double slDistanceDollars;
                    double tpDistanceDollars;

                    if (isGold)
                    {
                        // On Gold: If sl_pips is e.g. 35, it means $3.50. If 350, it also means $3.50 (350 * 0.01).
                        if (inSlPips >= 100.0)
                        {
                            slDistanceDollars = inSlPips * pipSize;
                        }
                        else if (inSlPips > 0)
                        {
                            slDistanceDollars = inSlPips * 0.10; // 35 * 0.10 = $3.50
                        }
                        else
                        {
                            slDistanceDollars = MinStopLossDollarsGold;
                        }

                        // Enforce minimum $3.50 buffer on Gold
                        if (slDistanceDollars < MinStopLossDollarsGold)
                        {
                            slDistanceDollars = MinStopLossDollarsGold;
                        }

                        if (inTpPips >= 100.0)
                        {
                            tpDistanceDollars = inTpPips * pipSize;
                        }
                        else if (inTpPips > 0)
                        {
                            tpDistanceDollars = inTpPips * 0.10; // 70 * 0.10 = $7.00
                        }
                        else
                        {
                            tpDistanceDollars = slDistanceDollars * 2.0;
                        }

                        // Enforce minimum 1:2 R:R ($7.00 TP minimum)
                        if (tpDistanceDollars < (slDistanceDollars * 2.0))
                        {
                            tpDistanceDollars = slDistanceDollars * 2.0;
                        }
                    }
                    else
                    {
                        // Standard Forex Pair
                        double minPips = 25.0;
                        double actualSlPips = inSlPips > minPips ? inSlPips : minPips;
                        double actualTpPips = inTpPips > (actualSlPips * 2.0) ? inTpPips : (actualSlPips * 2.0);
                        slDistanceDollars = actualSlPips * pipSize;
                        tpDistanceDollars = actualTpPips * pipSize;
                    }

                    // Convert exact dollar distances to cTrader Pip units for ExecuteMarketOrder
                    double slPipsForOrder = Math.Round(slDistanceDollars / pipSize, 1);
                    double tpPipsForOrder = Math.Round(tpDistanceDollars / pipSize, 1);

                    // Compute absolute target prices for safety verification
                    double refPrice = (tradeType == TradeType.Buy) ? sym.Ask : sym.Bid;
                    double targetSlPrice = (tradeType == TradeType.Buy) 
                        ? Math.Round(sym.Ask - slDistanceDollars, sym.Digits) 
                        : Math.Round(sym.Bid + slDistanceDollars, sym.Digits);
                    double targetTpPrice = (tradeType == TradeType.Buy) 
                        ? Math.Round(sym.Ask + tpDistanceDollars, sym.Digits) 
                        : Math.Round(sym.Bid - tpDistanceDollars, sym.Digits);

                    Print(string.Format(CultureInfo.InvariantCulture,
                        "🚀 Executing Order: {0} {1} {2:F2} Lots | Entry Ref: {3:F2} | SL Target: {4:F2} (${5:F2} / {6:F0} pips) | TP Target: {7:F2} (${8:F2} / {9:F0} pips)",
                        sym.Name, tradeType, volumeLots, refPrice, targetSlPrice, slDistanceDollars, slPipsForOrder, targetTpPrice, tpDistanceDollars, tpPipsForOrder));

                    TradeResult result = ExecuteMarketOrder(tradeType, sym.Name, volumeInUnits, comment, slPipsForOrder, tpPipsForOrder);

                    if (result != null && result.IsSuccessful && result.Position != null)
                    {
                        var pos = result.Position;

                        // Guarantee exact absolute SL/TP price modification
                        try
                        {
                            if (pos.StopLoss != targetSlPrice || pos.TakeProfit != targetTpPrice)
                            {
                                ModifyPosition(pos, targetSlPrice, targetTpPrice);
                            }
                        }
                        catch (Exception modEx)
                        {
                            Print("ModifyPosition Note: " + modEx.Message);
                        }

                        Print(string.Format(CultureInfo.InvariantCulture,
                            "✅ [ORDER FILLED & SECURED] Position #{0} | {1} {2} @ {3:F2} | SL: {4:F2} | TP: {5:F2}",
                            pos.Id, pos.SymbolName, pos.TradeType, pos.EntryPrice, pos.StopLoss, pos.TakeProfit));

                        httpStatus = 200;
                        return string.Format(CultureInfo.InvariantCulture,
                            "{{\"status\":\"SUCCESS\",\"position_id\":{0},\"order_id\":{0},\"symbol\":\"{1}\",\"trade_type\":\"{2}\",\"lots\":{3:F2},\"volume\":{4},\"entry_price\":{5},\"sl\":{6},\"tp\":{7},\"comment\":\"{8}\",\"account_id\":\"{9}\"}}",
                            pos.Id, pos.SymbolName, pos.TradeType.ToString().ToUpperInvariant(), volumeLots, pos.VolumeInUnits, pos.EntryPrice, pos.StopLoss ?? 0, pos.TakeProfit ?? 0, EscapeJson(comment), Account != null ? Account.Number.ToString() : "0");
                    }
                    else
                    {
                        string err = result != null ? (result.Error.HasValue ? result.Error.Value.ToString() : "Unknown Error") : "Execution returned null";
                        Print("🚨 Execution Failed: " + err);
                        httpStatus = 400;
                        return string.Format("{{\"status\":\"ERROR\",\"error\":\"{0}\"}}", EscapeJson(err));
                    }
                }
                catch (Exception ex)
                {
                    Print("ExecuteMarketOrder Exception: " + ex.Message);
                    httpStatus = 500;
                    return string.Format("{{\"status\":\"ERROR\",\"error\":\"{0}\"}}", EscapeJson(ex.Message));
                }
            }
        }

        private Symbol ResolveSymbol(string symbolStr)
        {
            if (string.IsNullOrEmpty(symbolStr)) return Symbol;
            string clean = symbolStr.ToUpperInvariant().Trim();
            return Symbols.GetSymbol(clean)
                ?? Symbols.GetSymbol(clean + ".pro")
                ?? Symbols.GetSymbol(clean + "m")
                ?? Symbols.GetSymbol(clean + "_i")
                ?? (clean.Contains("XAU") || clean.Contains("GOLD") ? (Symbols.GetSymbol("XAUUSD") ?? Symbols.GetSymbol("GOLD")) : null)
                ?? Symbol;
        }

        private void SendJsonResponse(HttpListenerResponse response, string json)
        {
            byte[] buffer = Encoding.UTF8.GetBytes(json);
            response.ContentLength64 = buffer.Length;
            using (var output = response.OutputStream)
            {
                output.Write(buffer, 0, buffer.Length);
            }
        }

        private string ExtractJsonValue(string json, string key)
        {
            if (string.IsNullOrEmpty(json) || string.IsNullOrEmpty(key)) return null;
            string pattern = "\"" + key + "\"";
            int idx = json.IndexOf(pattern, StringComparison.OrdinalIgnoreCase);
            if (idx == -1) return null;

            int colonIdx = json.IndexOf(':', idx + pattern.Length);
            if (colonIdx == -1) return null;

            int valStart = colonIdx + 1;
            while (valStart < json.Length && (json[valStart] == ' ' || json[valStart] == '\t' || json[valStart] == '\r' || json[valStart] == '\n'))
                valStart++;

            if (valStart >= json.Length) return null;

            if (json[valStart] == '"')
            {
                int endQuote = json.IndexOf('"', valStart + 1);
                if (endQuote != -1)
                    return json.Substring(valStart + 1, endQuote - valStart - 1);
            }
            else
            {
                int endIdx = valStart;
                while (endIdx < json.Length && json[endIdx] != ',' && json[endIdx] != '}' && json[endIdx] != ']' && json[endIdx] != '\r' && json[endIdx] != '\n')
                    endIdx++;
                return json.Substring(valStart, endIdx - valStart).Trim();
            }
            return null;
        }

        private string EscapeJson(string s)
        {
            if (string.IsNullOrEmpty(s)) return "";
            return s.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\n", "\\n").Replace("\r", "\\r");
        }

        protected override void OnStop()
        {
            try
            {
                _cts?.Cancel();
                if (_listener != null && _listener.IsListening)
                {
                    _listener.Stop();
                    _listener.Close();
                }
                Print("🛑 TradeTalk CleanBridge Stopped Cleanly.");
            }
            catch (Exception ex)
            {
                Print("OnStop Exception: " + ex.Message);
            }
        }
    }
}