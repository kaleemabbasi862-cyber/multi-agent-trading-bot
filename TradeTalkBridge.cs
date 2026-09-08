using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Globalization;
using cAlgo.API;
using cAlgo.API.Internals;

namespace cAlgo.Robots
{
    [Robot(TimeZone = TimeZones.UTC, AccessRights = AccessRights.FullAccess)]
    public class TradeTalkBridge : Robot
    {
        [Parameter("Port", DefaultValue = 5001, MinValue = 1024, MaxValue = 65535)]
        public int Port { get; set; }

        [Parameter("Max Concurrent Positions", DefaultValue = 1, MinValue = 1, MaxValue = 10)]
        public int MaxConcurrentPositions { get; set; }

        private HttpListener _listener;
        private CancellationTokenSource _cts;
        private Thread _listenerThread;
        private readonly object _orderLock = new object();

        protected override void OnStart()
        {
            _cts = new CancellationTokenSource();
            StartHttpBridgeServer();

            Print("======================================================================");
            Print("   TRADETALK AI - ULTRA-LOW LATENCY LOCAL CBOT WEBHOOK BRIDGE         ");
            Print("======================================================================");
            Print(string.Format("Account: #{0} ({1}) | Broker: {2}", Account.Number, Account.IsLive ? "LIVE" : "DEMO", Account.BrokerName));
            Print(string.Format(CultureInfo.InvariantCulture, "Balance: ${0:F2} | Equity: ${1:F2}", Account.Balance, Account.Equity));
            Print(string.Format("Listening on: http://127.0.0.1:{0}/trade/", Port));
            Print(string.Format("Max Positions: {0} | Min Hold Time: 5 min | Min SL Buffer: $2.50", MaxConcurrentPositions));
            Print("======================================================================");
        }

        private void StartHttpBridgeServer()
        {
            try
            {
                _listener = new HttpListener();
                string prefix1 = string.Format("http://127.0.0.1:{0}/trade/", Port);
                string prefix2 = string.Format("http://localhost:{0}/trade/", Port);

                _listener.Prefixes.Add(prefix1);
                try
                {
                    _listener.Prefixes.Add(prefix2);
                }
                catch { }

                _listener.Start();

                _listenerThread = new Thread(ListenLoop)
                {
                    IsBackground = true,
                    Name = "TradeTalkBridgeListener"
                };
                _listenerThread.Start();
                Print(string.Format("🟢 HTTP Webhook Bridge active at {0}", prefix1));
            }
            catch (Exception ex)
            {
                Print("🚨 Failed to start HTTP Bridge listener: " + ex.Message);
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
                    Print("Listener loop note: " + ex.Message);
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
                        Print("🚨 Error inside MainThread delegate: " + ex.ToString());
                        tcs.TrySetException(ex);
                    }
                });
            }
            catch (Exception ex)
            {
                Print("🚨 Error calling BeginInvokeOnMainThread: " + ex.ToString());
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

            // CORS headers
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

                if (request.HttpMethod == "GET")
                {
                    // Status / Healthcheck endpoint executed safely on Main Thread
                    string statusJson = RunOnMainThread(() =>
                    {
                        var posList = new List<string>();
                        if (Positions != null)
                        {
                            foreach (var p in Positions)
                            {
                                if (p == null) continue;
                                posList.Add(string.Format(CultureInfo.InvariantCulture,
                                    "{{\"id\":{0},\"symbol\":\"{1}\",\"side\":\"{2}\",\"lots\":{3},\"entry\":{4},\"sl\":{5},\"tp\":{6},\"pnl\":{7:F2}}}",
                                    p.Id, p.SymbolName ?? "", p.TradeType.ToString(), p.VolumeInUnits, p.EntryPrice, p.StopLoss ?? 0, p.TakeProfit ?? 0, p.NetProfit));
                            }
                        }

                        string accNum = Account != null ? Account.Number.ToString() : "5908018";
                        string broker = Account != null ? Account.BrokerName : "Spotware";
                        bool isLive = Account != null && Account.IsLive;
                        double bal = Account != null ? Account.Balance : 0.0;
                        double eq = Account != null ? Account.Equity : 0.0;
                        double marg = Account != null ? Account.Margin : 0.0;
                        double freeMarg = Account != null ? Account.FreeMargin : 0.0;
                        int count = Positions != null ? Positions.Count : 0;

                        return string.Format(CultureInfo.InvariantCulture,
                            "{{\"status\":\"ONLINE\",\"bridge\":\"TradeTalk Local cBot Webhook Bridge\",\"account_id\":\"{0}\",\"broker\":\"{1}\",\"is_live\":{2},\"balance\":{3:F2},\"equity\":{4:F2},\"margin\":{5:F2},\"free_margin\":{6:F2},\"open_positions_count\":{7},\"positions\":[{8}]}}",
                            accNum, broker, isLive ? "true" : "false", bal, eq, marg, freeMarg, count, string.Join(",", posList));
                    });

                    response.StatusCode = 200;
                    SendJsonResponse(response, statusJson);
                    return;
                }

                if (request.HttpMethod == "POST")
                {
                    string requestBody;
                    using (var reader = new StreamReader(request.InputStream, request.ContentEncoding))
                    {
                        requestBody = reader.ReadToEnd();
                    }

                    Print("📥 Incoming Bridge Trade Request: " + requestBody);

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

        private string HandleTradeExecution(string json, out int httpStatus)
        {
            lock (_orderLock)
            {
                try
                {
                    // Parse simple JSON parameters
                    string symbolStr = ExtractJsonValue(json, "symbol") ?? "XAUUSD";
                    string sideStr = (ExtractJsonValue(json, "side") ?? ExtractJsonValue(json, "action") ?? "BUY").ToUpperInvariant();
                    string comment = ExtractJsonValue(json, "comment") ?? "TradeTalk AI";
                    
                    double volumeLots = 0.01;
                    string volStr = ExtractJsonValue(json, "volume") ?? ExtractJsonValue(json, "lot_size") ?? ExtractJsonValue(json, "lots");
                    if (!string.IsNullOrEmpty(volStr))
                    {
                        double.TryParse(volStr, NumberStyles.Any, CultureInfo.InvariantCulture, out volumeLots);
                    }
                    if (volumeLots <= 0) volumeLots = 0.01;

                    // Parse SL and TP pips or price targets
                    double slPips = 0;
                    double tpPips = 0;
                    string slPipsStr = ExtractJsonValue(json, "stop_loss_pips") ?? ExtractJsonValue(json, "sl_pips");
                    string tpPipsStr = ExtractJsonValue(json, "take_profit_pips") ?? ExtractJsonValue(json, "tp_pips");
                    
                    if (!string.IsNullOrEmpty(slPipsStr)) double.TryParse(slPipsStr, NumberStyles.Any, CultureInfo.InvariantCulture, out slPips);
                    if (!string.IsNullOrEmpty(tpPipsStr)) double.TryParse(tpPipsStr, NumberStyles.Any, CultureInfo.InvariantCulture, out tpPips);

                    double slPrice = 0;
                    double tpPrice = 0;
                    string slPriceStr = ExtractJsonValue(json, "sl_price") ?? ExtractJsonValue(json, "sl");
                    string tpPriceStr = ExtractJsonValue(json, "tp_price") ?? ExtractJsonValue(json, "tp");
                    if (!string.IsNullOrEmpty(slPriceStr)) double.TryParse(slPriceStr, NumberStyles.Any, CultureInfo.InvariantCulture, out slPrice);
                    if (!string.IsNullOrEmpty(tpPriceStr)) double.TryParse(tpPriceStr, NumberStyles.Any, CultureInfo.InvariantCulture, out tpPrice);

                    // 0. Handle Close Order Request
                    if (sideStr == "CLOSE" || sideStr.Contains("CLOSE"))
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
                            if (openDurationSec < 300.0 && !isForce)
                            {
                                Print(string.Format("⏳ [HOLD TIME GUARD] Rejected Close for #{0}. Position open for {1:F0}s (< 300s / 5m min hold time).", targetPos.Id, openDurationSec));
                                httpStatus = 400;
                                return string.Format(CultureInfo.InvariantCulture,
                                    "{{\"status\":\"REJECTED\",\"error\":\"Minimum hold time (5m) not reached. Active for {0:F0}s / 300s.\"}}",
                                    openDurationSec);
                            }

                            var closeResult = ClosePosition(targetPos);
                            Print(string.Format("🛑 [CLOSED] Position #{0} ({1}) Closed via Webhook.", targetPos.Id, targetPos.SymbolName));
                            httpStatus = 200;
                            return string.Format("{{\"status\":\"SUCCESS\",\"message\":\"Position #{0} closed.\",\"position_id\":{0}}}", targetPos.Id);
                        }

                        httpStatus = 404;
                        return "{\"status\":\"ERROR\",\"error\":\"Position not found to close.\"}";
                    }

                    // 1. Position Count Limit Guard
                    if (Positions != null && Positions.Count >= MaxConcurrentPositions)
                    {
                        httpStatus = 400;
                        return string.Format("{{\"status\":\"REJECTED\",\"error\":\"Max positions limit ({0}) reached.\",\"open_positions\":{1}}}", MaxConcurrentPositions, Positions.Count);
                    }

                    // 2. Resolve Symbol on Broker
                    Symbol sym = ResolveSymbol(symbolStr);
                    if (sym == null)
                    {
                        httpStatus = 400;
                        return string.Format("{{\"status\":\"REJECTED\",\"error\":\"Symbol '{0}' not found on broker.\"}}", symbolStr);
                    }

                    TradeType tradeType = sideStr.Contains("BUY") ? TradeType.Buy : TradeType.Sell;

                    // 3. Convert Volume to Broker Units
                    double volumeInUnits = sym.QuantityToVolumeInUnits(volumeLots);

                    // 4. Calculate Pips if exact price was provided
                    double pipSize = sym.PipSize > 0 ? sym.PipSize : 0.01;
                    bool isGold = sym.Name.ToUpperInvariant().Contains("XAU") || sym.Name.ToUpperInvariant().Contains("GOLD");

                    if (slPips <= 0 && slPrice > 0)
                    {
                        double entryRef = tradeType == TradeType.Buy ? sym.Ask : sym.Bid;
                        slPips = Math.Abs(entryRef - slPrice) / pipSize;
                    }
                    if (tpPips <= 0 && tpPrice > 0)
                    {
                        double entryRef = tradeType == TradeType.Buy ? sym.Ask : sym.Bid;
                        tpPips = Math.Abs(tpPrice - entryRef) / pipSize;
                    }

                    // Minimum Stop Loss buffer enforcement (at least $2.50 breathing room on Gold)
                    if (isGold)
                    {
                        double minGoldPips = 2.50 / pipSize; // Guarantee $2.50 price buffer
                        if (slPips < minGoldPips) slPips = minGoldPips;
                        if (tpPips < slPips * 2.0) tpPips = slPips * 2.0; // Maintain at least 1:2 R:R
                    }
                    else
                    {
                        if (slPips < 25.0) slPips = 25.0;
                        if (tpPips < slPips * 2.0) tpPips = slPips * 2.0;
                    }

                    // Default safe 1:2 R:R if not set ($6.00 SL / $12.00 TP on Gold)
                    if (slPips <= 0) slPips = isGold ? (6.00 / pipSize) : 40.0;
                    if (tpPips <= 0) tpPips = slPips * 2.0;

                    Print(string.Format(CultureInfo.InvariantCulture,
                        "🚀 Executing Order on {0}: {1} {2} Lots ({3} units) | SL Pips: {4:F1}, TP Pips: {5:F1}",
                        sym.Name, tradeType, volumeLots, volumeInUnits, slPips, tpPips));

                    TradeResult result = ExecuteMarketOrder(tradeType, sym, volumeInUnits, comment, slPips, tpPips);

                    if (result != null && result.IsSuccessful && result.Position != null)
                    {
                        var pos = result.Position;
                        Print(string.Format(CultureInfo.InvariantCulture,
                            "✅ [ORDER FILLED] Position #{0} | Symbol: {1} | Side: {2} | Entry: {3} | SL: {4} | TP: {5}",
                            pos.Id, pos.SymbolName, pos.TradeType, pos.EntryPrice, pos.StopLoss, pos.TakeProfit));

                        httpStatus = 200;
                        return string.Format(CultureInfo.InvariantCulture,
                            "{{\"status\":\"SUCCESS\",\"position_id\":{0},\"order_id\":{0},\"symbol\":\"{1}\",\"side\":\"{2}\",\"lots\":{3},\"volume\":{4},\"entry_price\":{5},\"sl\":{6},\"tp\":{7},\"comment\":\"{8}\",\"account_id\":\"{9}\"}}",
                            pos.Id, pos.SymbolName, pos.TradeType, volumeLots, pos.VolumeInUnits, pos.EntryPrice, pos.StopLoss ?? 0, pos.TakeProfit ?? 0, EscapeJson(comment), Account != null ? Account.Number.ToString() : "5908018");
                    }
                    else
                    {
                        string err = result != null ? result.Error.ToString() : "Execution returned null";
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
                Print("🛑 TradeTalk Local cBot Webhook Bridge Stopped Cleanly.");
            }
            catch (Exception ex)
            {
                Print("OnStop Exception: " + ex.Message);
            }
        }
    }
}
