var Rs = { exports: {} }, et = {};
var v0;
function Uy() {
  if (v0) return et;
  v0 = 1;
  var o = /* @__PURE__ */ Symbol.for("react.transitional.element"), _ = /* @__PURE__ */ Symbol.for("react.portal"), E = /* @__PURE__ */ Symbol.for("react.fragment"), r = /* @__PURE__ */ Symbol.for("react.strict_mode"), C = /* @__PURE__ */ Symbol.for("react.profiler"), J = /* @__PURE__ */ Symbol.for("react.consumer"), M = /* @__PURE__ */ Symbol.for("react.context"), A = /* @__PURE__ */ Symbol.for("react.forward_ref"), k = /* @__PURE__ */ Symbol.for("react.suspense"), L = /* @__PURE__ */ Symbol.for("react.memo"), R = /* @__PURE__ */ Symbol.for("react.lazy"), p = /* @__PURE__ */ Symbol.for("react.activity"), U = /* @__PURE__ */ Symbol.for("react.view_transition"), X = Symbol.iterator;
  function G(s) {
    return s === null || typeof s != "object" ? null : (s = X && s[X] || s["@@iterator"], typeof s == "function" ? s : null);
  }
  var q = {
    isMounted: function() {
      return !1;
    },
    enqueueForceUpdate: function() {
    },
    enqueueReplaceState: function() {
    },
    enqueueSetState: function() {
    }
  }, at = Object.assign, Ot = {};
  function ht(s, T, O) {
    this.props = s, this.context = T, this.refs = Ot, this.updater = O || q;
  }
  ht.prototype.isReactComponent = {}, ht.prototype.setState = function(s, T) {
    if (typeof s != "object" && typeof s != "function" && s != null)
      throw Error(
        "takes an object of state variables to update or a function which returns an object of state variables."
      );
    this.updater.enqueueSetState(this, s, T, "setState");
  }, ht.prototype.forceUpdate = function(s) {
    this.updater.enqueueForceUpdate(this, s, "forceUpdate");
  };
  function Pt() {
  }
  Pt.prototype = ht.prototype;
  function St(s, T, O) {
    this.props = s, this.context = T, this.refs = Ot, this.updater = O || q;
  }
  var Mt = St.prototype = new Pt();
  Mt.constructor = St, at(Mt, ht.prototype), Mt.isPureReactComponent = !0;
  var pt = Array.isArray;
  function ut() {
  }
  var lt = { H: null, A: null, T: null, S: null }, Ht = Object.prototype.hasOwnProperty;
  function $(s, T, O) {
    var D = O.ref;
    return {
      $$typeof: o,
      type: s,
      key: T,
      ref: D !== void 0 ? D : null,
      props: O
    };
  }
  function _t(s, T) {
    return $(s.type, T, s.props);
  }
  function gt(s) {
    return typeof s == "object" && s !== null && s.$$typeof === o;
  }
  function qt(s) {
    var T = { "=": "=0", ":": "=2" };
    return "$" + s.replace(/[=:]/g, function(O) {
      return T[O];
    });
  }
  var cl = /\/+/g;
  function Yt(s, T) {
    return typeof s == "object" && s !== null && s.key != null ? qt("" + s.key) : T.toString(36);
  }
  function B(s) {
    switch (s.status) {
      case "fulfilled":
        return s.value;
      case "rejected":
        throw s.reason;
      default:
        switch (typeof s.status == "string" ? s.then(ut, ut) : (s.status = "pending", s.then(
          function(T) {
            s.status === "pending" && (s.status = "fulfilled", s.value = T);
          },
          function(T) {
            s.status === "pending" && (s.status = "rejected", s.reason = T);
          }
        )), s.status) {
          case "fulfilled":
            return s.value;
          case "rejected":
            throw s.reason;
        }
    }
    throw s;
  }
  function W(s, T, O, D, Y) {
    var w = typeof s;
    (w === "undefined" || w === "boolean") && (s = null);
    var I = !1;
    if (s === null) I = !0;
    else
      switch (w) {
        case "bigint":
        case "string":
        case "number":
          I = !0;
          break;
        case "object":
          switch (s.$$typeof) {
            case o:
            case _:
              I = !0;
              break;
            case R:
              return I = s._init, W(
                I(s._payload),
                T,
                O,
                D,
                Y
              );
          }
      }
    if (I)
      return Y = Y(s), I = D === "" ? "." + Yt(s, 0) : D, pt(Y) ? (O = "", I != null && (O = I.replace(cl, "$&/") + "/"), W(Y, T, O, "", function(Ut) {
        return Ut;
      })) : Y != null && (gt(Y) && (Y = _t(
        Y,
        O + (Y.key == null || s && s.key === Y.key ? "" : ("" + Y.key).replace(
          cl,
          "$&/"
        ) + "/") + I
      )), T.push(Y)), 1;
    I = 0;
    var H = D === "" ? "." : D + ":";
    if (pt(s))
      for (var V = 0; V < s.length; V++)
        D = s[V], w = H + Yt(D, V), I += W(
          D,
          T,
          O,
          w,
          Y
        );
    else if (V = G(s), typeof V == "function")
      for (s = V.call(s), V = 0; !(D = s.next()).done; )
        D = D.value, w = H + Yt(D, V++), I += W(
          D,
          T,
          O,
          w,
          Y
        );
    else if (w === "object") {
      if (typeof s.then == "function")
        return W(
          B(s),
          T,
          O,
          D,
          Y
        );
      throw T = String(s), Error(
        "Objects are not valid as a React child (found: " + (T === "[object Object]" ? "object with keys {" + Object.keys(s).join(", ") + "}" : T) + "). If you meant to render a collection of children, use an array instead."
      );
    }
    return I;
  }
  function tt(s, T, O) {
    if (s == null) return s;
    var D = [], Y = 0;
    return W(s, D, "", "", function(w) {
      return T.call(O, w, Y++);
    }), D;
  }
  function Tt(s) {
    if (s._status === -1) {
      var T = s._result, O = T();
      O.then(
        function(D) {
          (s._status === 0 || s._status === -1) && (s._status = 1, s._result = D, O.status === void 0 && (O.status = "fulfilled", O.value = D));
        },
        function(D) {
          (s._status === 0 || s._status === -1) && (s._status = 2, s._result = D, O.status === void 0 && (O.status = "rejected", O.reason = D));
        }
      ), s._status === -1 && (s._status = 0, s._result = O);
    }
    if (s._status === 1) return s._result.default;
    throw s._result;
  }
  var dt = typeof reportError == "function" ? reportError : function(s) {
    if (typeof window == "object" && typeof window.ErrorEvent == "function") {
      var T = new window.ErrorEvent("error", {
        bubbles: !0,
        cancelable: !0,
        message: typeof s == "object" && s !== null && typeof s.message == "string" ? String(s.message) : String(s),
        error: s
      });
      if (!window.dispatchEvent(T)) return;
    } else if (typeof process == "object" && typeof process.emit == "function") {
      process.emit("uncaughtException", s);
      return;
    }
    console.error(s);
  };
  function sl(s) {
    var T = lt.T, O = {};
    O.types = T !== null ? T.types : null, lt.T = O;
    try {
      var D = s(), Y = lt.S;
      Y !== null && Y(O, D), typeof D == "object" && D !== null && typeof D.then == "function" && D.then(ut, dt);
    } catch (w) {
      dt(w);
    } finally {
      T !== null && O.types !== null && (T.types = O.types), lt.T = T;
    }
  }
  function Zl(s) {
    var T = lt.T;
    if (T !== null) {
      var O = T.types;
      O === null ? T.types = [s] : O.indexOf(s) === -1 && O.push(s);
    } else sl(Zl.bind(null, s));
  }
  var x = {
    map: tt,
    forEach: function(s, T, O) {
      tt(
        s,
        function() {
          T.apply(this, arguments);
        },
        O
      );
    },
    count: function(s) {
      var T = 0;
      return tt(s, function() {
        T++;
      }), T;
    },
    toArray: function(s) {
      return tt(s, function(T) {
        return T;
      }) || [];
    },
    only: function(s) {
      if (!gt(s))
        throw Error(
          "React.Children.only expected to receive a single React element child."
        );
      return s;
    }
  };
  return et.Activity = p, et.Children = x, et.Component = ht, et.Fragment = E, et.Profiler = C, et.PureComponent = St, et.StrictMode = r, et.Suspense = k, et.ViewTransition = U, et.__CLIENT_INTERNALS_DO_NOT_USE_OR_WARN_USERS_THEY_CANNOT_UPGRADE = lt, et.__COMPILER_RUNTIME = {
    __proto__: null,
    c: function(s) {
      return lt.H.useMemoCache(s);
    }
  }, et.addTransitionType = Zl, et.cache = function(s) {
    return function() {
      return s.apply(null, arguments);
    };
  }, et.cacheSignal = function() {
    return null;
  }, et.cloneElement = function(s, T, O) {
    if (s == null)
      throw Error(
        "The argument must be a React element, but you passed " + s + "."
      );
    var D = at({}, s.props), Y = s.key;
    if (T != null)
      for (w in T.key !== void 0 && (Y = "" + T.key), T)
        !Ht.call(T, w) || w === "key" || w === "__self" || w === "__source" || w === "ref" && T.ref === void 0 || (D[w] = T[w]);
    var w = arguments.length - 2;
    if (w === 1) D.children = O;
    else if (1 < w) {
      for (var I = Array(w), H = 0; H < w; H++)
        I[H] = arguments[H + 2];
      D.children = I;
    }
    return $(s.type, Y, D);
  }, et.createContext = function(s) {
    return s = {
      $$typeof: M,
      _currentValue: s,
      _currentValue2: s,
      _threadCount: 0,
      Provider: null,
      Consumer: null
    }, s.Provider = s, s.Consumer = {
      $$typeof: J,
      _context: s
    }, s;
  }, et.createElement = function(s, T, O) {
    var D, Y = {}, w = null;
    if (T != null)
      for (D in T.key !== void 0 && (w = "" + T.key), T)
        Ht.call(T, D) && D !== "key" && D !== "__self" && D !== "__source" && (Y[D] = T[D]);
    var I = arguments.length - 2;
    if (I === 1) Y.children = O;
    else if (1 < I) {
      for (var H = Array(I), V = 0; V < I; V++)
        H[V] = arguments[V + 2];
      Y.children = H;
    }
    if (s && s.defaultProps)
      for (D in I = s.defaultProps, I)
        Y[D] === void 0 && (Y[D] = I[D]);
    return $(s, w, Y);
  }, et.createRef = function() {
    return { current: null };
  }, et.forwardRef = function(s) {
    return { $$typeof: A, render: s };
  }, et.isValidElement = gt, et.lazy = function(s) {
    return {
      $$typeof: R,
      _payload: { _status: -1, _result: s },
      _init: Tt
    };
  }, et.memo = function(s, T) {
    return {
      $$typeof: L,
      type: s,
      compare: T === void 0 ? null : T
    };
  }, et.startTransition = sl, et.unstable_useCacheRefresh = function() {
    return lt.H.useCacheRefresh();
  }, et.use = function(s) {
    return lt.H.use(s);
  }, et.useActionState = function(s, T, O) {
    return lt.H.useActionState(s, T, O);
  }, et.useCallback = function(s, T) {
    return lt.H.useCallback(s, T);
  }, et.useContext = function(s) {
    return lt.H.useContext(s);
  }, et.useDebugValue = function() {
  }, et.useDeferredValue = function(s, T) {
    return lt.H.useDeferredValue(s, T);
  }, et.useEffect = function(s, T) {
    return lt.H.useEffect(s, T);
  }, et.useEffectEvent = function(s) {
    return lt.H.useEffectEvent(s);
  }, et.useId = function() {
    return lt.H.useId();
  }, et.useImperativeHandle = function(s, T, O) {
    return lt.H.useImperativeHandle(s, T, O);
  }, et.useInsertionEffect = function(s, T) {
    return lt.H.useInsertionEffect(s, T);
  }, et.useLayoutEffect = function(s, T) {
    return lt.H.useLayoutEffect(s, T);
  }, et.useMemo = function(s, T) {
    return lt.H.useMemo(s, T);
  }, et.useOptimistic = function(s, T) {
    return lt.H.useOptimistic(s, T);
  }, et.useReducer = function(s, T, O) {
    return lt.H.useReducer(s, T, O);
  }, et.useRef = function(s) {
    return lt.H.useRef(s);
  }, et.useState = function(s) {
    return lt.H.useState(s);
  }, et.useSyncExternalStore = function(s, T, O) {
    return lt.H.useSyncExternalStore(
      s,
      T,
      O
    );
  }, et.useTransition = function() {
    return lt.H.useTransition();
  }, et.version = "19.3.0", et;
}
var h0;
function Qs() {
  return h0 || (h0 = 1, Rs.exports = Uy()), Rs.exports;
}
var F = Qs(), Ds = { exports: {} }, rn = {}, Us = { exports: {} }, js = {};
var y0;
function jy() {
  return y0 || (y0 = 1, (function(o) {
    function _(B, W) {
      var tt = B.length;
      B.push(W);
      t: for (; 0 < tt; ) {
        var Tt = tt - 1 >>> 1, dt = B[Tt];
        if (0 < C(dt, W))
          B[Tt] = W, B[tt] = dt, tt = Tt;
        else break t;
      }
    }
    function E(B) {
      return B.length === 0 ? null : B[0];
    }
    function r(B) {
      if (B.length === 0) return null;
      var W = B[0], tt = B.pop();
      if (tt !== W) {
        B[0] = tt;
        t: for (var Tt = 0, dt = B.length, sl = dt >>> 1; Tt < sl; ) {
          var Zl = 2 * (Tt + 1) - 1, x = B[Zl], s = Zl + 1, T = B[s];
          if (0 > C(x, tt))
            s < dt && 0 > C(T, x) ? (B[Tt] = T, B[s] = tt, Tt = s) : (B[Tt] = x, B[Zl] = tt, Tt = Zl);
          else if (s < dt && 0 > C(T, tt))
            B[Tt] = T, B[s] = tt, Tt = s;
          else break t;
        }
      }
      return W;
    }
    function C(B, W) {
      var tt = B.sortIndex - W.sortIndex;
      return tt !== 0 ? tt : B.id - W.id;
    }
    if (o.unstable_now = void 0, typeof performance == "object" && typeof performance.now == "function") {
      var J = performance;
      o.unstable_now = function() {
        return J.now();
      };
    } else {
      var M = Date, A = M.now();
      o.unstable_now = function() {
        return M.now() - A;
      };
    }
    var k = [], L = [], R = 1, p = null, U = 3, X = !1, G = !1, q = !1, at = !1, Ot = typeof setTimeout == "function" ? setTimeout : null, ht = typeof clearTimeout == "function" ? clearTimeout : null, Pt = typeof setImmediate < "u" ? setImmediate : null;
    function St(B) {
      for (var W = E(L); W !== null; ) {
        if (W.callback === null) r(L);
        else if (W.startTime <= B)
          r(L), W.sortIndex = W.expirationTime, _(k, W);
        else break;
        W = E(L);
      }
    }
    function Mt(B) {
      if (q = !1, St(B), !G)
        if (E(k) !== null)
          G = !0, pt || (pt = !0, gt());
        else {
          var W = E(L);
          W !== null && Yt(Mt, W.startTime - B);
        }
    }
    var pt = !1, ut = -1, lt = 5, Ht = -1;
    function $() {
      return at ? !0 : !(o.unstable_now() - Ht < lt);
    }
    function _t() {
      if (at = !1, pt) {
        var B = o.unstable_now();
        Ht = B;
        var W = !0;
        try {
          t: {
            G = !1, q && (q = !1, ht(ut), ut = -1), X = !0;
            var tt = U;
            try {
              l: {
                for (St(B), p = E(k); p !== null && !(p.expirationTime > B && $()); ) {
                  var Tt = p.callback;
                  if (typeof Tt == "function") {
                    p.callback = null, U = p.priorityLevel;
                    var dt = Tt(
                      p.expirationTime <= B
                    );
                    if (B = o.unstable_now(), typeof dt == "function") {
                      p.callback = dt, St(B), W = !0;
                      break l;
                    }
                    p === E(k) && r(k), St(B);
                  } else r(k);
                  p = E(k);
                }
                if (p !== null) W = !0;
                else {
                  var sl = E(L);
                  sl !== null && Yt(
                    Mt,
                    sl.startTime - B
                  ), W = !1;
                }
              }
              break t;
            } finally {
              p = null, U = tt, X = !1;
            }
            W = void 0;
          }
        } finally {
          W ? gt() : pt = !1;
        }
      }
    }
    var gt;
    if (typeof Pt == "function")
      gt = function() {
        Pt(_t);
      };
    else if (typeof MessageChannel < "u") {
      var qt = new MessageChannel(), cl = qt.port2;
      qt.port1.onmessage = _t, gt = function() {
        cl.postMessage(null);
      };
    } else
      gt = function() {
        Ot(_t, 0);
      };
    function Yt(B, W) {
      ut = Ot(function() {
        B(o.unstable_now());
      }, W);
    }
    o.unstable_IdlePriority = 5, o.unstable_ImmediatePriority = 1, o.unstable_LowPriority = 4, o.unstable_NormalPriority = 3, o.unstable_Profiling = null, o.unstable_UserBlockingPriority = 2, o.unstable_cancelCallback = function(B) {
      B.callback = null;
    }, o.unstable_forceFrameRate = function(B) {
      0 > B || 125 < B ? console.error(
        "forceFrameRate takes a positive int between 0 and 125, forcing frame rates higher than 125 fps is not supported"
      ) : lt = 0 < B ? Math.floor(1e3 / B) : 5;
    }, o.unstable_getCurrentPriorityLevel = function() {
      return U;
    }, o.unstable_next = function(B) {
      switch (U) {
        case 1:
        case 2:
        case 3:
          var W = 3;
          break;
        default:
          W = U;
      }
      var tt = U;
      U = W;
      try {
        return B();
      } finally {
        U = tt;
      }
    }, o.unstable_requestPaint = function() {
      at = !0;
    }, o.unstable_runWithPriority = function(B, W) {
      switch (B) {
        case 1:
        case 2:
        case 3:
        case 4:
        case 5:
          break;
        default:
          B = 3;
      }
      var tt = U;
      U = B;
      try {
        return W();
      } finally {
        U = tt;
      }
    }, o.unstable_scheduleCallback = function(B, W, tt) {
      var Tt = o.unstable_now();
      switch (typeof tt == "object" && tt !== null ? (tt = tt.delay, tt = typeof tt == "number" && 0 < tt ? Tt + tt : Tt) : tt = Tt, B) {
        case 1:
          var dt = -1;
          break;
        case 2:
          dt = 250;
          break;
        case 5:
          dt = 1073741823;
          break;
        case 4:
          dt = 1e4;
          break;
        default:
          dt = 5e3;
      }
      return dt = tt + dt, B = {
        id: R++,
        callback: W,
        priorityLevel: B,
        startTime: tt,
        expirationTime: dt,
        sortIndex: -1
      }, tt > Tt ? (B.sortIndex = tt, _(L, B), E(k) === null && B === E(L) && (q ? (ht(ut), ut = -1) : q = !0, Yt(Mt, tt - Tt))) : (B.sortIndex = dt, _(k, B), G || X || (G = !0, pt || (pt = !0, gt()))), B;
    }, o.unstable_shouldYield = $, o.unstable_wrapCallback = function(B) {
      var W = U;
      return function() {
        var tt = U;
        U = W;
        try {
          return B.apply(this, arguments);
        } finally {
          U = tt;
        }
      };
    };
  })(js)), js;
}
var g0;
function Hy() {
  return g0 || (g0 = 1, Us.exports = jy()), Us.exports;
}
var Hs = { exports: {} }, il = {};
var b0;
function By() {
  if (b0) return il;
  b0 = 1;
  var o = Qs();
  function _(R) {
    var p = "https://react.dev/errors/" + R;
    if (1 < arguments.length) {
      p += "?args[]=" + encodeURIComponent(arguments[1]);
      for (var U = 2; U < arguments.length; U++)
        p += "&args[]=" + encodeURIComponent(arguments[U]);
    }
    return "Minified React error #" + R + "; visit " + p + " for the full message or use the non-minified dev environment for full errors and additional helpful warnings.";
  }
  function E() {
  }
  var r = {
    d: {
      f: E,
      r: function() {
        throw Error(_(522));
      },
      D: E,
      C: E,
      L: E,
      m: E,
      X: E,
      S: E,
      M: E
    },
    p: 0,
    findDOMNode: null
  }, C = /* @__PURE__ */ Symbol.for("react.portal"), J = /* @__PURE__ */ Symbol.for("react.recoverable"), M = /* @__PURE__ */ Symbol.for("react.optimistic_key");
  function A(R, p, U) {
    var X = 3 < arguments.length && arguments[3] !== void 0 ? arguments[3] : null;
    return {
      $$typeof: C,
      key: X == null ? null : X === M ? M : "" + X,
      children: R,
      containerInfo: p,
      implementation: U
    };
  }
  var k = o.__CLIENT_INTERNALS_DO_NOT_USE_OR_WARN_USERS_THEY_CANNOT_UPGRADE;
  function L(R, p) {
    if (R === "font") return "";
    if (typeof p == "string")
      return p === "use-credentials" ? p : "";
  }
  return il.__DOM_INTERNALS_DO_NOT_USE_OR_WARN_USERS_THEY_CANNOT_UPGRADE = r, il.browser = function(R) {
    return { $$typeof: J, _reason: R };
  }, il.createPortal = function(R, p) {
    var U = 2 < arguments.length && arguments[2] !== void 0 ? arguments[2] : null;
    if (!p || p.nodeType !== 1 && p.nodeType !== 9 && p.nodeType !== 11)
      throw Error(_(299));
    return A(R, p, null, U);
  }, il.flushSync = function(R) {
    var p = k.T, U = r.p;
    try {
      if (k.T = null, r.p = 2, R) return R();
    } finally {
      k.T = p, r.p = U, r.d.f();
    }
  }, il.preconnect = function(R, p) {
    typeof R == "string" && (p ? (p = p.crossOrigin, p = typeof p == "string" ? p === "use-credentials" ? p : "" : void 0) : p = null, r.d.C(R, p));
  }, il.prefetchDNS = function(R) {
    typeof R == "string" && r.d.D(R);
  }, il.preinit = function(R, p) {
    if (typeof R == "string" && p && typeof p.as == "string") {
      var U = p.as, X = L(U, p.crossOrigin), G = typeof p.integrity == "string" ? p.integrity : void 0, q = typeof p.fetchPriority == "string" ? p.fetchPriority : void 0;
      U === "style" ? r.d.S(
        R,
        typeof p.precedence == "string" ? p.precedence : void 0,
        {
          crossOrigin: X,
          integrity: G,
          fetchPriority: q
        }
      ) : U === "script" && r.d.X(R, {
        crossOrigin: X,
        integrity: G,
        fetchPriority: q,
        nonce: typeof p.nonce == "string" ? p.nonce : void 0
      });
    }
  }, il.preinitModule = function(R, p) {
    if (typeof R == "string")
      if (typeof p == "object" && p !== null) {
        if (p.as == null || p.as === "script") {
          var U = L(
            p.as,
            p.crossOrigin
          );
          r.d.M(R, {
            crossOrigin: U,
            integrity: typeof p.integrity == "string" ? p.integrity : void 0,
            nonce: typeof p.nonce == "string" ? p.nonce : void 0,
            fetchPriority: typeof p.fetchPriority == "string" ? p.fetchPriority : void 0
          });
        }
      } else p == null && r.d.M(R);
  }, il.preload = function(R, p) {
    if (typeof R == "string" && typeof p == "object" && p !== null && typeof p.as == "string") {
      var U = p.as, X = L(U, p.crossOrigin);
      r.d.L(R, U, {
        crossOrigin: X,
        integrity: typeof p.integrity == "string" ? p.integrity : void 0,
        nonce: typeof p.nonce == "string" ? p.nonce : void 0,
        type: typeof p.type == "string" ? p.type : void 0,
        fetchPriority: typeof p.fetchPriority == "string" ? p.fetchPriority : void 0,
        referrerPolicy: typeof p.referrerPolicy == "string" ? p.referrerPolicy : void 0,
        imageSrcSet: typeof p.imageSrcSet == "string" ? p.imageSrcSet : void 0,
        imageSizes: typeof p.imageSizes == "string" ? p.imageSizes : void 0,
        media: typeof p.media == "string" ? p.media : void 0
      });
    }
  }, il.preloadModule = function(R, p) {
    if (typeof R == "string")
      if (p) {
        var U = L(p.as, p.crossOrigin);
        r.d.m(R, {
          as: typeof p.as == "string" && p.as !== "script" ? p.as : void 0,
          crossOrigin: U,
          integrity: typeof p.integrity == "string" ? p.integrity : void 0,
          nonce: typeof p.nonce == "string" ? p.nonce : void 0,
          fetchPriority: typeof p.fetchPriority == "string" ? p.fetchPriority : void 0
        });
      } else r.d.m(R);
  }, il.requestFormReset = function(R) {
    r.d.r(R);
  }, il.unstable_batchedUpdates = function(R, p) {
    return R(p);
  }, il.useFormState = function(R, p, U) {
    return k.H.useFormState(R, p, U);
  }, il.useFormStatus = function() {
    return k.H.useHostTransitionStatus();
  }, il.version = "19.3.0", il;
}
var S0;
function qy() {
  if (S0) return Hs.exports;
  S0 = 1;
  function o() {
    if (!(typeof __REACT_DEVTOOLS_GLOBAL_HOOK__ > "u" || typeof __REACT_DEVTOOLS_GLOBAL_HOOK__.checkDCE != "function"))
      try {
        __REACT_DEVTOOLS_GLOBAL_HOOK__.checkDCE(o);
      } catch (_) {
        console.error(_);
      }
  }
  return o(), Hs.exports = By(), Hs.exports;
}
var p0;
function Yy() {
  if (p0) return rn;
  p0 = 1;
  var o = Hy(), _ = Qs(), E = qy();
  function r(t) {
    var l = "https://react.dev/errors/" + t;
    if (1 < arguments.length) {
      l += "?args[]=" + encodeURIComponent(arguments[1]);
      for (var e = 2; e < arguments.length; e++)
        l += "&args[]=" + encodeURIComponent(arguments[e]);
    }
    return "Minified React error #" + t + "; visit " + l + " for the full message or use the non-minified dev environment for full errors and additional helpful warnings.";
  }
  function C(t) {
    return !(!t || t.nodeType !== 1 && t.nodeType !== 9 && t.nodeType !== 11);
  }
  function J(t) {
    for (var l = t, e = l; e && !e.alternate; )
      l = e, (l.flags & 4098) !== 0 && (t = l.return), e = l.return;
    for (; l.return; ) l = l.return;
    return l.tag === 3 ? t : null;
  }
  function M(t) {
    if (t.tag === 13) {
      var l = t.memoizedState;
      if (l === null && (t = t.alternate, t !== null && (l = t.memoizedState)), l !== null) return l.dehydrated;
    }
    return null;
  }
  function A(t) {
    if (t.tag === 31) {
      var l = t.memoizedState;
      if (l === null && (t = t.alternate, t !== null && (l = t.memoizedState)), l !== null) return l.dehydrated;
    }
    return null;
  }
  function k(t) {
    if (J(t) !== t)
      throw Error(r(188));
  }
  function L(t) {
    var l = t.alternate;
    if (!l) {
      if (l = J(t), l === null) throw Error(r(188));
      return l !== t ? null : t;
    }
    for (var e = t, a = l; ; ) {
      var u = e.return;
      if (u === null) break;
      var n = u.alternate;
      if (n === null) {
        if (a = u.return, a !== null) {
          e = a;
          continue;
        }
        break;
      }
      if (u.child === n.child) {
        for (n = u.child; n; ) {
          if (n === e) return k(u), t;
          if (n === a) return k(u), l;
          n = n.sibling;
        }
        throw Error(r(188));
      }
      if (e.return !== a.return) e = u, a = n;
      else {
        for (var i = !1, c = u.child; c; ) {
          if (c === e) {
            i = !0, e = u, a = n;
            break;
          }
          if (c === a) {
            i = !0, a = u, e = n;
            break;
          }
          c = c.sibling;
        }
        if (!i) {
          for (c = n.child; c; ) {
            if (c === e) {
              i = !0, e = n, a = u;
              break;
            }
            if (c === a) {
              i = !0, a = n, e = u;
              break;
            }
            c = c.sibling;
          }
          if (!i) throw Error(r(189));
        }
      }
      if (e.alternate !== a) throw Error(r(190));
    }
    if (e.tag !== 3) throw Error(r(188));
    return e.stateNode.current === e ? t : l;
  }
  function R(t) {
    var l = t.tag;
    if (l === 5 || l === 26 || l === 27 || l === 6) return t;
    for (t = t.child; t !== null; ) {
      if (l = R(t), l !== null) return l;
      t = t.sibling;
    }
    return null;
  }
  function p(t, l, e, a, u, n) {
    for (; t !== null; ) {
      if ((t.tag === 5 || t.tag === 27 || t.tag === 6) && e(t, a, u, n) || (t.tag !== 22 || t.memoizedState === null) && (l || t.tag !== 5 && t.tag !== 27) && p(
        t.child,
        l,
        e,
        a,
        u,
        n
      ))
        return !0;
      t = t.sibling;
    }
    return !1;
  }
  function U(t) {
    for (t = t.return; t !== null; ) {
      if (t.tag === 3 || t.tag === 5 || t.tag === 27) return t;
      t = t.return;
    }
    return null;
  }
  function X(t) {
    var l = !1;
    for (t = t.return; t !== null && (t.tag === 4 && (l = !0), !(t.tag === 3 || t.tag === 5 || t.tag === 27)); )
      t = t.return;
    return l;
  }
  function G(t) {
    var l = [null, null], e = U(t);
    return e === null || q(
      l,
      t,
      e.child,
      { foundSelf: !1 }
    ), l;
  }
  function q(t, l, e, a) {
    for (; e !== null; ) {
      if (e === l) a.foundSelf = !0;
      else if (e.tag === 5 || e.tag === 27 || e.tag === 6) {
        if (a.foundSelf) return t[1] = e, !0;
        t[0] = e;
      } else if ((e.tag !== 22 || e.memoizedState === null) && q(
        t,
        l,
        e.child,
        a
      ))
        return !0;
      e = e.sibling;
    }
    return !1;
  }
  function at(t) {
    switch (t.tag) {
      case 5:
      case 27:
      case 6:
        return t.stateNode;
      case 3:
        return t.stateNode.containerInfo;
      default:
        throw Error(r(559));
    }
  }
  var Ot = null, ht = null;
  function Pt(t, l, e) {
    return t === e ? !0 : t === l ? (Ot = t, !0) : !1;
  }
  function St(t, l, e) {
    return t === e ? (ht = t, !1) : t === l ? (ht !== null && (Ot = t), !0) : !1;
  }
  function Mt(t) {
    if (t === null) return null;
    do
      t = t === null ? null : t.return;
    while (t && t.tag !== 5 && t.tag !== 27 && t.tag !== 3);
    return t || null;
  }
  function pt(t, l, e) {
    for (var a = 0, u = t; u; u = e(u)) a++;
    u = 0;
    for (var n = l; n; n = e(n)) u++;
    for (; 0 < a - u; ) t = e(t), a--;
    for (; 0 < u - a; ) l = e(l), u--;
    for (; a--; ) {
      if (t === l || l !== null && t === l.alternate)
        return t;
      t = e(t), l = e(l);
    }
    return null;
  }
  var ut = Object.assign, lt = /* @__PURE__ */ Symbol.for("react.element"), Ht = /* @__PURE__ */ Symbol.for("react.transitional.element"), $ = /* @__PURE__ */ Symbol.for("react.portal"), _t = /* @__PURE__ */ Symbol.for("react.fragment"), gt = /* @__PURE__ */ Symbol.for("react.strict_mode"), qt = /* @__PURE__ */ Symbol.for("react.profiler"), cl = /* @__PURE__ */ Symbol.for("react.consumer"), Yt = /* @__PURE__ */ Symbol.for("react.context"), B = /* @__PURE__ */ Symbol.for("react.forward_ref"), W = /* @__PURE__ */ Symbol.for("react.suspense"), tt = /* @__PURE__ */ Symbol.for("react.suspense_list"), Tt = /* @__PURE__ */ Symbol.for("react.memo"), dt = /* @__PURE__ */ Symbol.for("react.lazy"), sl = /* @__PURE__ */ Symbol.for("react.activity"), Zl = /* @__PURE__ */ Symbol.for("react.legacy_hidden"), x = /* @__PURE__ */ Symbol.for("react.memo_cache_sentinel"), s = /* @__PURE__ */ Symbol.for("react.view_transition"), T = /* @__PURE__ */ Symbol.for("react.recoverable"), O = Symbol.iterator;
  function D(t) {
    return t === null || typeof t != "object" ? null : (t = O && t[O] || t["@@iterator"], typeof t == "function" ? t : null);
  }
  var Y = /* @__PURE__ */ Symbol.for("react.client.reference");
  function w(t) {
    if (t == null) return null;
    if (typeof t == "function")
      return t.$$typeof === Y ? null : t.displayName || t.name || null;
    if (typeof t == "string") return t;
    switch (t) {
      case _t:
        return "Fragment";
      case qt:
        return "Profiler";
      case gt:
        return "StrictMode";
      case W:
        return "Suspense";
      case tt:
        return "SuspenseList";
      case sl:
        return "Activity";
      case s:
        return "ViewTransition";
    }
    if (typeof t == "object")
      switch (t.$$typeof) {
        case $:
          return "Portal";
        case Yt:
          return t.displayName || "Context";
        case cl:
          return (t._context.displayName || "Context") + ".Consumer";
        case B:
          var l = t.render;
          return t = t.displayName, t || (t = l.displayName || l.name || "", t = t !== "" ? "ForwardRef(" + t + ")" : "ForwardRef"), t;
        case Tt:
          return l = t.displayName || null, l !== null ? l : w(t.type) || "Memo";
        case dt:
          l = t._payload, t = t._init;
          try {
            return w(t(l));
          } catch {
          }
      }
    return null;
  }
  var I = Array.isArray, H = _.__CLIENT_INTERNALS_DO_NOT_USE_OR_WARN_USERS_THEY_CANNOT_UPGRADE, V = E.__DOM_INTERNALS_DO_NOT_USE_OR_WARN_USERS_THEY_CANNOT_UPGRADE, Ut = {
    pending: !1,
    data: null,
    method: null,
    action: null
  }, oe = [], wl = -1;
  function Dl(t) {
    return { current: t };
  }
  function Qt(t) {
    0 > wl || (t.current = oe[wl], oe[wl] = null, wl--);
  }
  function Ct(t, l) {
    wl++, oe[wl] = t.current, t.current = l;
  }
  var Il = Dl(null), yu = Dl(null), Oe = Dl(null), yn = Dl(null);
  function gn(t, l) {
    switch (Ct(Oe, l), Ct(yu, t), Ct(Il, null), l.nodeType) {
      case 9:
      case 11:
        t = (t = l.documentElement) && (t = t.namespaceURI) ? xm(t) : 0;
        break;
      default:
        if (t = l.tagName, l = l.namespaceURI)
          l = xm(l), t = Em(l, t);
        else
          switch (t) {
            case "svg":
              t = 1;
              break;
            case "math":
              t = 2;
              break;
            default:
              t = 0;
          }
    }
    Qt(Il), Ct(Il, t);
  }
  function za() {
    Qt(Il), Qt(yu), Qt(Oe);
  }
  function Wi(t) {
    var l = t.memoizedState;
    l !== null && (mu._currentValue = l.memoizedState, Ct(yn, t)), l = Il.current;
    var e = Em(l, t.type);
    l !== e && (Ct(yu, t), Ct(Il, e));
  }
  function bn(t) {
    yu.current === t && (Qt(Il), Qt(yu)), yn.current === t && (Qt(yn), mu._currentValue = Ut);
  }
  var Fi, Zs;
  function Ae(t) {
    if (Fi === void 0)
      try {
        throw Error();
      } catch (e) {
        var l = e.stack.trim().match(/\n( *(at )?)/);
        Fi = l && l[1] || "", Zs = -1 < e.stack.indexOf(`
    at`) ? " (<anonymous>)" : -1 < e.stack.indexOf("@") ? "@unknown:0:0" : "";
      }
    return `
` + Fi + t + Zs;
  }
  var Ii = !1;
  function Pi(t, l) {
    if (!t || Ii) return "";
    Ii = !0;
    var e = Error.prepareStackTrace;
    Error.prepareStackTrace = void 0;
    try {
      var a = {
        DetermineComponentFrameRoot: function() {
          try {
            if (l) {
              var z = function() {
                throw Error();
              };
              if (Object.defineProperty(z.prototype, "props", {
                set: function() {
                  throw Error();
                }
              }), typeof Reflect == "object" && Reflect.construct) {
                try {
                  Reflect.construct(z, []);
                } catch (j) {
                  var v = j;
                }
                Reflect.construct(t, [], z);
              } else {
                try {
                  z.call();
                } catch (j) {
                  v = j;
                }
                z = !1;
                try {
                  var b = Object.getOwnPropertyDescriptor(
                    t.prototype,
                    "props"
                  );
                  Object.defineProperty(t.prototype, "props", {
                    configurable: !0,
                    set: function() {
                      throw Error();
                    }
                  }), z = !0, new t();
                } finally {
                  z && (b !== void 0 ? Object.defineProperty(t.prototype, "props", b) : delete t.prototype.props);
                }
              }
            } else {
              try {
                throw Error();
              } catch (j) {
                v = j;
              }
              (z = t()) && typeof z.catch == "function" && z.catch(function() {
              });
            }
          } catch (j) {
            if (j && v && typeof j.stack == "string")
              return [j.stack, v.stack];
          }
          return [null, null];
        }
      };
      a.DetermineComponentFrameRoot.displayName = "DetermineComponentFrameRoot";
      var u = Object.getOwnPropertyDescriptor(
        a.DetermineComponentFrameRoot,
        "name"
      );
      u && u.configurable && Object.defineProperty(
        a.DetermineComponentFrameRoot,
        "name",
        { value: "DetermineComponentFrameRoot" }
      );
      var n = a.DetermineComponentFrameRoot(), i = n[0], c = n[1];
      if (i && c) {
        var f = i.split(`
`), y = c.split(`
`);
        for (u = a = 0; a < f.length && !f[a].includes("DetermineComponentFrameRoot"); )
          a++;
        for (; u < y.length && !y[u].includes(
          "DetermineComponentFrameRoot"
        ); )
          u++;
        if (a === f.length || u === y.length)
          for (a = f.length - 1, u = y.length - 1; 1 <= a && 0 <= u && f[a] !== y[u]; )
            u--;
        for (; 1 <= a && 0 <= u; a--, u--)
          if (f[a] !== y[u]) {
            if (a !== 1 || u !== 1)
              do
                if (a--, u--, 0 > u || f[a] !== y[u]) {
                  var S = `
` + f[a].replace(" at new ", " at ");
                  return t.displayName && S.includes("<anonymous>") && (S = S.replace("<anonymous>", t.displayName)), S;
                }
              while (1 <= a && 0 <= u);
            break;
          }
      }
    } finally {
      Ii = !1, Error.prepareStackTrace = e;
    }
    return (e = t ? t.displayName || t.name : "") ? Ae(e) : "";
  }
  function q0(t, l) {
    switch (t.tag) {
      case 26:
      case 27:
      case 5:
        return Ae(t.type);
      case 16:
        return Ae("Lazy");
      case 13:
        return t.child !== l && l !== null ? Ae("Suspense Fallback") : Ae("Suspense");
      case 19:
        return Ae("SuspenseList");
      case 0:
      case 15:
        return Pi(t.type, !1);
      case 11:
        return Pi(t.type.render, !1);
      case 1:
        return Pi(t.type, !0);
      case 31:
        return Ae("Activity");
      case 30:
        return Ae("ViewTransition");
      default:
        return "";
    }
  }
  function ws(t) {
    try {
      var l = "", e = null;
      do
        l += q0(t, e), e = t, t = t.return;
      while (t);
      return l;
    } catch (a) {
      return `
Error generating stack: ` + a.message + `
` + a.stack;
    }
  }
  var tc = Object.prototype.hasOwnProperty, lc = o.unstable_scheduleCallback, ec = o.unstable_cancelCallback, Y0 = o.unstable_shouldYield, X0 = o.unstable_requestPaint, pl = o.unstable_now, G0 = o.unstable_getCurrentPriorityLevel, Vs = o.unstable_ImmediatePriority, Ks = o.unstable_UserBlockingPriority, Sn = o.unstable_NormalPriority, Q0 = o.unstable_LowPriority, Js = o.unstable_IdlePriority, L0 = o.log, Z0 = o.unstable_setDisableYieldValue, gu = null, _l = null;
  function Me(t) {
    if (typeof L0 == "function" && Z0(t), _l && typeof _l.setStrictMode == "function")
      try {
        _l.setStrictMode(gu, t);
      } catch {
      }
  }
  var Tl = Math.clz32 ? Math.clz32 : K0, w0 = Math.log, V0 = Math.LN2;
  function K0(t) {
    return t >>>= 0, t === 0 ? 32 : 31 - (w0(t) / V0 | 0) | 0;
  }
  var pn = 256, _n = 262144, Tn = 4194304;
  function ea(t) {
    var l = t & 42;
    if (l !== 0) return l;
    switch (t & -t) {
      case 1:
        return 1;
      case 2:
        return 2;
      case 4:
        return 4;
      case 8:
        return 8;
      case 16:
        return 16;
      case 32:
        return 32;
      case 64:
        return 64;
      case 128:
        return 128;
      case 256:
      case 512:
      case 1024:
      case 2048:
      case 4096:
      case 8192:
      case 16384:
      case 32768:
      case 65536:
      case 131072:
        return t & -t;
      case 262144:
      case 524288:
      case 1048576:
      case 2097152:
        return t & 3932160;
      case 4194304:
      case 8388608:
      case 16777216:
      case 33554432:
        return t & 62914560;
      case 67108864:
        return 67108864;
      case 134217728:
        return 134217728;
      case 268435456:
        return 268435456;
      case 536870912:
        return 536870912;
      case 1073741824:
        return 0;
      default:
        return t;
    }
  }
  function xn(t, l, e) {
    var a = t.pendingLanes;
    if (a === 0) return 0;
    var u = 0, n = t.suspendedLanes, i = t.pingedLanes;
    t = t.warmLanes;
    var c = a & 134217727;
    return c !== 0 ? (a = c & ~n, a !== 0 ? u = ea(a) : (i &= c, i !== 0 ? u = ea(i) : e || (e = c & ~t, e !== 0 && (u = ea(e))))) : (c = a & ~n, c !== 0 ? u = ea(c) : i !== 0 ? u = ea(i) : e || (e = a & ~t, e !== 0 && (u = ea(e)))), u === 0 ? 0 : l !== 0 && l !== u && (l & n) === 0 && (n = u & -u, e = l & -l, n >= e || n === 32 && (e & 4194048) !== 0) ? l : u;
  }
  function bu(t, l) {
    return (t.pendingLanes & ~(t.suspendedLanes & ~t.pingedLanes) & l) === 0;
  }
  function ks(t, l) {
    (l & 8) !== 0 && (l |= l & 32);
    var e = t.entangledLanes;
    if (e !== 0)
      for (t = t.entanglements, e &= l; 0 < e; ) {
        var a = 31 - Tl(e), u = 1 << a;
        l |= t[a], e &= ~u;
      }
    return l;
  }
  function J0(t, l) {
    switch (t) {
      case 1:
      case 2:
      case 4:
      case 8:
      case 64:
        return l + 250;
      case 16:
      case 32:
      case 128:
      case 256:
      case 512:
      case 1024:
      case 2048:
      case 4096:
      case 8192:
      case 16384:
      case 32768:
      case 65536:
      case 131072:
      case 262144:
      case 524288:
      case 1048576:
      case 2097152:
        return l + 5e3;
      case 4194304:
      case 8388608:
      case 16777216:
      case 33554432:
        return -1;
      case 67108864:
      case 134217728:
      case 268435456:
      case 536870912:
      case 1073741824:
        return -1;
      default:
        return -1;
    }
  }
  function $s() {
    var t = Tn;
    return Tn <<= 1, (Tn & 62914560) === 0 && (Tn = 4194304), t;
  }
  function ac(t) {
    for (var l = [], e = 0; 31 > e; e++) l.push(t);
    return l;
  }
  function Su(t, l) {
    t.pendingLanes |= l, l !== 268435456 && (t.suspendedLanes = 0, t.pingedLanes = 0, t.warmLanes = 0);
  }
  function k0(t, l, e, a, u, n) {
    var i = t.pendingLanes;
    t.pendingLanes = e, t.suspendedLanes = 0, t.pingedLanes = 0, t.warmLanes = 0, t.expiredLanes &= e, t.entangledLanes &= e, t.errorRecoveryDisabledLanes &= e, t.shellSuspendCounter = 0;
    var c = t.entanglements, f = t.expirationTimes, y = t.hiddenUpdates;
    for (e = i & ~e; 0 < e; ) {
      var S = 31 - Tl(e), z = 1 << S;
      c[S] = 0, f[S] = -1;
      var v = y[S];
      if (v !== null)
        for (y[S] = null, S = 0; S < v.length; S++) {
          var b = v[S];
          b !== null && (b.lane &= -536870913);
        }
      e &= ~z;
    }
    a !== 0 && Ws(t, a, 0), n !== 0 && u === 0 && t.tag !== 0 && (t.suspendedLanes |= n & ~(i & ~l));
  }
  function Ws(t, l, e) {
    t.pendingLanes |= l, t.suspendedLanes &= ~l;
    var a = 31 - Tl(l);
    t.entangledLanes |= l, t.entanglements[a] = t.entanglements[a] | 1073741824 | e & 261930;
  }
  function Fs(t, l) {
    var e = t.entangledLanes |= l;
    for (t = t.entanglements; e; ) {
      var a = 31 - Tl(e), u = 1 << a;
      u & l | t[a] & l && (t[a] |= l), e &= ~u;
    }
  }
  function Is(t, l) {
    var e = l & -l;
    return e = (e & 42) !== 0 ? 1 : uc(e), (e & (t.suspendedLanes | l)) !== 0 ? 0 : e;
  }
  function uc(t) {
    switch (t) {
      case 2:
        t = 1;
        break;
      case 8:
        t = 4;
        break;
      case 32:
        t = 16;
        break;
      case 256:
      case 512:
      case 1024:
      case 2048:
      case 4096:
      case 8192:
      case 16384:
      case 32768:
      case 65536:
      case 131072:
      case 262144:
      case 524288:
      case 1048576:
      case 2097152:
      case 4194304:
      case 8388608:
      case 16777216:
      case 33554432:
        t = 128;
        break;
      case 268435456:
        t = 134217728;
        break;
      default:
        t = 0;
    }
    return t;
  }
  function nc(t) {
    return t &= -t, 2 < t ? 8 < t ? (t & 134217727) !== 0 ? 32 : 268435456 : 8 : 2;
  }
  function Ps() {
    var t = V.p;
    return t !== 0 ? t : (t = window.event, t === void 0 ? 32 : c0(t.type));
  }
  function to(t, l) {
    var e = V.p;
    try {
      return V.p = t, l();
    } finally {
      V.p = e;
    }
  }
  var re = Math.random().toString(36).slice(2), tl = "__reactFiber$" + re, vl = "__reactProps$" + re, Oa = "__reactContainer$" + re, lo = "__reactEvents$" + re, $0 = "__reactListeners$" + re, W0 = "__reactHandles$" + re, eo = "__reactResources$" + re, pu = "__reactMarker$" + re, En = "__reactLoad$" + re;
  function Nn(t) {
    delete t[tl], delete t[vl], delete t[$0], delete t[W0];
  }
  function aa(t) {
    var l;
    if (l = t[tl]) return l;
    for (var e = t.parentNode; e; ) {
      if (l = e[Oa] || e[tl]) {
        if (e = l.alternate, l.child !== null || e !== null && e.child !== null)
          for (t = Qm(t); t !== null; ) {
            if (e = t[tl]) return e;
            t = Qm(t);
          }
        return l;
      }
      t = e, e = t.parentNode;
    }
    return null;
  }
  function Aa(t) {
    if (t = t[tl] || t[Oa]) {
      var l = t.tag;
      if (l === 5 || l === 6 || l === 13 || l === 31 || l === 26 || l === 27 || l === 3)
        return t;
    }
    return null;
  }
  function _u(t) {
    var l = t.tag;
    if (l === 5 || l === 26 || l === 27 || l === 6) return t.stateNode;
    throw Error(r(33));
  }
  function Ma(t) {
    var l = t[eo];
    return l || (l = t[eo] = { hoistableStyles: /* @__PURE__ */ new Map(), hoistableScripts: /* @__PURE__ */ new Map() }), l;
  }
  function $t(t) {
    t[pu] = !0;
  }
  function ao(t) {
    t[En] = void 0;
  }
  var uo = /* @__PURE__ */ new Set(), no = {};
  function ua(t, l) {
    Ca(t, l), Ca(t + "Capture", l);
  }
  function Ca(t, l) {
    for (no[t] = l, t = 0; t < l.length; t++)
      uo.add(l[t]);
  }
  var F0 = RegExp(
    "^[:A-Z_a-z\\u00C0-\\u00D6\\u00D8-\\u00F6\\u00F8-\\u02FF\\u0370-\\u037D\\u037F-\\u1FFF\\u200C-\\u200D\\u2070-\\u218F\\u2C00-\\u2FEF\\u3001-\\uD7FF\\uF900-\\uFDCF\\uFDF0-\\uFFFD][:A-Z_a-z\\u00C0-\\u00D6\\u00D8-\\u00F6\\u00F8-\\u02FF\\u0370-\\u037D\\u037F-\\u1FFF\\u200C-\\u200D\\u2070-\\u218F\\u2C00-\\u2FEF\\u3001-\\uD7FF\\uF900-\\uFDCF\\uFDF0-\\uFFFD\\-.0-9\\u00B7\\u0300-\\u036F\\u203F-\\u2040]*$"
  ), io = {}, co = {};
  function I0(t) {
    return tc.call(co, t) ? !0 : tc.call(io, t) ? !1 : F0.test(t) ? co[t] = !0 : (io[t] = !0, !1);
  }
  var vt = !1;
  function fo() {
    var t = vt;
    return vt = !1, t;
  }
  function zn(t, l, e) {
    if (I0(l))
      if (e === null) t.removeAttribute(l);
      else {
        switch (typeof e) {
          case "undefined":
          case "function":
          case "symbol":
            t.removeAttribute(l);
            return;
          case "boolean":
            var a = l.toLowerCase().slice(0, 5);
            if (a !== "data-" && a !== "aria-") {
              t.removeAttribute(l);
              return;
            }
        }
        t.setAttribute(l, e);
      }
  }
  function On(t, l, e) {
    if (e === null) t.removeAttribute(l);
    else {
      switch (typeof e) {
        case "undefined":
        case "function":
        case "symbol":
        case "boolean":
          t.removeAttribute(l);
          return;
      }
      t.setAttribute(l, e);
    }
  }
  function de(t, l, e, a) {
    if (a === null) t.removeAttribute(e);
    else {
      switch (typeof a) {
        case "undefined":
        case "function":
        case "symbol":
        case "boolean":
          t.removeAttribute(e);
          return;
      }
      t.setAttributeNS(l, e, a);
    }
  }
  function xl(t) {
    switch (typeof t) {
      case "bigint":
      case "boolean":
      case "number":
      case "string":
      case "undefined":
        return t;
      case "object":
        return t;
      default:
        return "";
    }
  }
  function so(t) {
    var l = t.type;
    return (t = t.nodeName) && t.toLowerCase() === "input" && (l === "checkbox" || l === "radio");
  }
  function P0(t, l, e) {
    var a = Object.getOwnPropertyDescriptor(
      t.constructor.prototype,
      l
    );
    if (!t.hasOwnProperty(l) && typeof a < "u" && typeof a.get == "function" && typeof a.set == "function") {
      var u = a.get, n = a.set;
      return Object.defineProperty(t, l, {
        configurable: !0,
        get: function() {
          return u.call(this);
        },
        set: function(i) {
          e = "" + i, n.call(this, i);
        }
      }), Object.defineProperty(t, l, {
        enumerable: a.enumerable
      }), {
        getValue: function() {
          return e;
        },
        setValue: function(i) {
          e = "" + i;
        },
        stopTracking: function() {
          t._valueTracker = null, delete t[l];
        }
      };
    }
  }
  function ic(t) {
    if (!t._valueTracker) {
      var l = so(t) ? "checked" : "value";
      t._valueTracker = P0(
        t,
        l,
        "" + t[l]
      );
    }
  }
  function oo(t) {
    if (!t) return !1;
    var l = t._valueTracker;
    if (!l) return !0;
    var e = l.getValue(), a = "";
    return t && (a = so(t) ? t.checked ? "true" : "false" : t.value), t = a, t !== e ? (l.setValue(t), !0) : !1;
  }
  var tv = /[\n"\\]/g;
  function Ul(t) {
    return t.replace(
      tv,
      function(l) {
        return "\\" + l.charCodeAt(0).toString(16) + " ";
      }
    );
  }
  function cc(t, l, e, a, u, n, i, c) {
    t.name = "", i != null && typeof i != "function" && typeof i != "symbol" && typeof i != "boolean" ? t.type = i : t.removeAttribute("type"), l != null ? i === "number" ? (l === 0 && t.value === "" || t.value != l) && (t.value = "" + xl(l)) : t.value !== "" + xl(l) && (t.value = "" + xl(l)) : i !== "submit" && i !== "reset" || t.removeAttribute("value"), l != null ? i === "number" && t.value == l ? fc(t, xl(t.value)) : fc(t, xl(l)) : e != null ? fc(t, xl(e)) : a != null && t.removeAttribute("value"), u == null && n != null && (t.defaultChecked = !!n), u != null && (t.checked = u && typeof u != "function" && typeof u != "symbol"), c != null && typeof c != "function" && typeof c != "symbol" && typeof c != "boolean" ? t.name = "" + xl(c) : t.removeAttribute("name");
  }
  function ro(t, l, e, a, u, n, i, c) {
    if (n != null && typeof n != "function" && typeof n != "symbol" && typeof n != "boolean" && (t.type = n), l != null || e != null) {
      if (!(n !== "submit" && n !== "reset" || l != null)) {
        ic(t);
        return;
      }
      e = e != null ? "" + xl(e) : "", l = l != null ? "" + xl(l) : e, c || l === t.value || (t.value = l), t.defaultValue = l;
    }
    a = a ?? u, a = typeof a != "function" && typeof a != "symbol" && !!a, t.checked = c ? t.checked : !!a, t.defaultChecked = !!a, i != null && typeof i != "function" && typeof i != "symbol" && typeof i != "boolean" && (t.name = i), ic(t);
  }
  function fc(t, l) {
    t.defaultValue !== "" + l && (t.defaultValue = "" + l);
  }
  function Ra(t, l, e, a) {
    if (t = t.options, l) {
      l = {};
      for (var u = 0; u < e.length; u++)
        l["$" + e[u]] = !0;
      for (e = 0; e < t.length; e++)
        u = l.hasOwnProperty("$" + t[e].value), t[e].selected !== u && (t[e].selected = u), u && a && (t[e].defaultSelected = !0);
    } else {
      for (e = "" + xl(e), l = null, u = 0; u < t.length; u++) {
        if (t[u].value === e) {
          t[u].selected = !0, a && (t[u].defaultSelected = !0);
          return;
        }
        l !== null || t[u].disabled || (l = t[u]);
      }
      l !== null && (l.selected = !0);
    }
  }
  function mo(t, l, e) {
    if (l != null && (l = "" + xl(l), l !== t.value && (t.value = l), e == null)) {
      t.defaultValue !== l && (t.defaultValue = l);
      return;
    }
    t.defaultValue = e != null ? "" + xl(e) : "";
  }
  function vo(t, l, e, a) {
    if (l == null) {
      if (a != null) {
        if (e != null) throw Error(r(92));
        if (I(a)) {
          if (1 < a.length) throw Error(r(93));
          a = a[0];
        }
        e = a;
      }
      e == null && (e = ""), l = e;
    }
    e = xl(l), t.defaultValue = e, a = t.textContent, a === e && a !== "" && a !== null && (t.value = a), ic(t);
  }
  function Da(t, l) {
    if (l) {
      var e = t.firstChild;
      if (e && e === t.lastChild && e.nodeType === 3) {
        e.nodeValue = l;
        return;
      }
    }
    t.textContent = l;
  }
  var lv = new Set(
    "animationIterationCount aspectRatio borderImageOutset borderImageSlice borderImageWidth boxFlex boxFlexGroup boxOrdinalGroup columnCount columns flex flexGrow flexPositive flexShrink flexNegative flexOrder gridArea gridRow gridRowEnd gridRowSpan gridRowStart gridColumn gridColumnEnd gridColumnSpan gridColumnStart fontWeight lineClamp lineHeight opacity order orphans scale tabSize widows zIndex zoom fillOpacity floodOpacity stopOpacity strokeDasharray strokeDashoffset strokeMiterlimit strokeOpacity strokeWidth MozAnimationIterationCount MozBoxFlex MozBoxFlexGroup MozLineClamp msAnimationIterationCount msFlex msZoom msFlexGrow msFlexNegative msFlexOrder msFlexPositive msFlexShrink msGridColumn msGridColumnSpan msGridRow msGridRowSpan WebkitAnimationIterationCount WebkitBoxFlex WebKitBoxFlexGroup WebkitBoxOrdinalGroup WebkitColumnCount WebkitColumns WebkitFlex WebkitFlexGrow WebkitFlexPositive WebkitFlexShrink WebkitLineClamp".split(
      " "
    )
  );
  function ho(t, l, e) {
    var a = l.indexOf("--") === 0;
    e == null || typeof e == "boolean" || e === "" ? a ? t.setProperty(l, "") : l === "float" ? t.cssFloat = "" : t[l] = "" : a ? t.setProperty(l, e) : typeof e != "number" || e === 0 || lv.has(l) ? l === "float" ? t.cssFloat = e : t[l] = ("" + e).trim() : t[l] = e + "px";
  }
  function yo(t, l, e) {
    if (l != null && typeof l != "object")
      throw Error(r(62));
    if (t = t.style, e != null) {
      for (var a in e)
        !e.hasOwnProperty(a) || l != null && l.hasOwnProperty(a) || (a.indexOf("--") === 0 ? t.setProperty(a, "") : a === "float" ? t.cssFloat = "" : t[a] = "", vt = !0);
      for (var u in l)
        a = l[u], l.hasOwnProperty(u) && e[u] !== a && (ho(t, u, a), vt = !0);
    } else
      for (var n in l)
        l.hasOwnProperty(n) && ho(t, n, l[n]);
  }
  function sc(t) {
    if (t.indexOf("-") === -1) return !1;
    switch (t) {
      case "annotation-xml":
      case "color-profile":
      case "font-face":
      case "font-face-src":
      case "font-face-uri":
      case "font-face-format":
      case "font-face-name":
      case "missing-glyph":
        return !1;
      default:
        return !0;
    }
  }
  var ev = /* @__PURE__ */ new Map([
    ["acceptCharset", "accept-charset"],
    ["htmlFor", "for"],
    ["httpEquiv", "http-equiv"],
    ["crossOrigin", "crossorigin"],
    ["accentHeight", "accent-height"],
    ["alignmentBaseline", "alignment-baseline"],
    ["arabicForm", "arabic-form"],
    ["baselineShift", "baseline-shift"],
    ["capHeight", "cap-height"],
    ["clipPath", "clip-path"],
    ["clipRule", "clip-rule"],
    ["colorInterpolation", "color-interpolation"],
    ["colorInterpolationFilters", "color-interpolation-filters"],
    ["colorProfile", "color-profile"],
    ["colorRendering", "color-rendering"],
    ["dominantBaseline", "dominant-baseline"],
    ["enableBackground", "enable-background"],
    ["fillOpacity", "fill-opacity"],
    ["fillRule", "fill-rule"],
    ["floodColor", "flood-color"],
    ["floodOpacity", "flood-opacity"],
    ["fontFamily", "font-family"],
    ["fontSize", "font-size"],
    ["fontSizeAdjust", "font-size-adjust"],
    ["fontStretch", "font-stretch"],
    ["fontStyle", "font-style"],
    ["fontVariant", "font-variant"],
    ["fontWeight", "font-weight"],
    ["glyphName", "glyph-name"],
    ["glyphOrientationHorizontal", "glyph-orientation-horizontal"],
    ["glyphOrientationVertical", "glyph-orientation-vertical"],
    ["horizAdvX", "horiz-adv-x"],
    ["horizOriginX", "horiz-origin-x"],
    ["imageRendering", "image-rendering"],
    ["letterSpacing", "letter-spacing"],
    ["lightingColor", "lighting-color"],
    ["markerEnd", "marker-end"],
    ["markerMid", "marker-mid"],
    ["markerStart", "marker-start"],
    ["maskType", "mask-type"],
    ["overlinePosition", "overline-position"],
    ["overlineThickness", "overline-thickness"],
    ["paintOrder", "paint-order"],
    ["panose-1", "panose-1"],
    ["pointerEvents", "pointer-events"],
    ["renderingIntent", "rendering-intent"],
    ["shapeRendering", "shape-rendering"],
    ["stopColor", "stop-color"],
    ["stopOpacity", "stop-opacity"],
    ["strikethroughPosition", "strikethrough-position"],
    ["strikethroughThickness", "strikethrough-thickness"],
    ["strokeDasharray", "stroke-dasharray"],
    ["strokeDashoffset", "stroke-dashoffset"],
    ["strokeLinecap", "stroke-linecap"],
    ["strokeLinejoin", "stroke-linejoin"],
    ["strokeMiterlimit", "stroke-miterlimit"],
    ["strokeOpacity", "stroke-opacity"],
    ["strokeWidth", "stroke-width"],
    ["textAnchor", "text-anchor"],
    ["textDecoration", "text-decoration"],
    ["textRendering", "text-rendering"],
    ["transformOrigin", "transform-origin"],
    ["underlinePosition", "underline-position"],
    ["underlineThickness", "underline-thickness"],
    ["unicodeBidi", "unicode-bidi"],
    ["unicodeRange", "unicode-range"],
    ["unitsPerEm", "units-per-em"],
    ["vAlphabetic", "v-alphabetic"],
    ["vHanging", "v-hanging"],
    ["vIdeographic", "v-ideographic"],
    ["vMathematical", "v-mathematical"],
    ["vectorEffect", "vector-effect"],
    ["vertAdvY", "vert-adv-y"],
    ["vertOriginX", "vert-origin-x"],
    ["vertOriginY", "vert-origin-y"],
    ["wordSpacing", "word-spacing"],
    ["writingMode", "writing-mode"],
    ["xmlnsXlink", "xmlns:xlink"],
    ["xHeight", "x-height"]
  ]), av = /^[\u0000-\u001F ]*j[\r\n\t]*a[\r\n\t]*v[\r\n\t]*a[\r\n\t]*s[\r\n\t]*c[\r\n\t]*r[\r\n\t]*i[\r\n\t]*p[\r\n\t]*t[\r\n\t]*:/i;
  function An(t) {
    return av.test("" + t) ? "javascript:throw new Error('React has blocked a javascript: URL as a security precaution.')" : t;
  }
  function Pl() {
  }
  var oc = null;
  function rc(t) {
    return t = t.target || t.srcElement || window, t.correspondingUseElement && (t = t.correspondingUseElement), t.nodeType === 3 ? t.parentNode : t;
  }
  var Ua = null, ja = null;
  function go(t) {
    var l = Aa(t);
    if (l && (t = l.stateNode)) {
      var e = t[vl] || null;
      t: switch (t = l.stateNode, l.type) {
        case "input":
          if (cc(
            t,
            e.value,
            e.defaultValue,
            e.defaultValue,
            e.checked,
            e.defaultChecked,
            e.type,
            e.name
          ), l = e.name, e.type === "radio" && l != null) {
            for (e = t; e.parentNode; ) e = e.parentNode;
            for (e = e.querySelectorAll(
              'input[name="' + Ul(
                "" + l
              ) + '"][type="radio"]'
            ), l = 0; l < e.length; l++) {
              var a = e[l];
              if (a !== t && a.form === t.form) {
                var u = a[vl] || null;
                if (!u) throw Error(r(90));
                cc(
                  a,
                  u.value,
                  u.defaultValue,
                  u.defaultValue,
                  u.checked,
                  u.defaultChecked,
                  u.type,
                  u.name
                );
              }
            }
            for (l = 0; l < e.length; l++)
              a = e[l], a.form === t.form && oo(a);
          }
          break t;
        case "textarea":
          mo(t, e.value, e.defaultValue);
          break t;
        case "select":
          l = e.value, l != null && Ra(t, !!e.multiple, l, !1);
      }
    }
  }
  var dc = !1;
  function bo(t, l, e) {
    if (dc) return t(l, e);
    dc = !0;
    try {
      var a = t(l);
      return a;
    } finally {
      if (dc = !1, (Ua !== null || ja !== null) && (Ai(), Ua && (l = Ua, t = ja, ja = Ua = null, go(l), t)))
        for (l = 0; l < t.length; l++) go(t[l]);
    }
  }
  function Tu(t, l) {
    var e = t.stateNode;
    if (e === null) return null;
    var a = e[vl] || null;
    if (a === null) return null;
    e = a[l];
    t: switch (l) {
      case "onClick":
      case "onClickCapture":
      case "onDoubleClick":
      case "onDoubleClickCapture":
      case "onMouseDown":
      case "onMouseDownCapture":
      case "onMouseMove":
      case "onMouseMoveCapture":
      case "onMouseUp":
      case "onMouseUpCapture":
      case "onMouseEnter":
        (a = !a.disabled) || (t = t.type, a = !(t === "button" || t === "input" || t === "select" || t === "textarea")), t = !a;
        break t;
      default:
        t = !1;
    }
    if (t) return null;
    if (e && typeof e != "function")
      throw Error(
        r(231, l, typeof e)
      );
    return e;
  }
  var me = !(typeof window > "u" || typeof window.document > "u" || typeof window.document.createElement > "u"), mc = !1;
  if (me)
    try {
      var xu = {};
      Object.defineProperty(xu, "passive", {
        get: function() {
          mc = !0;
        }
      }), window.addEventListener("test", xu, xu), window.removeEventListener("test", xu, xu);
    } catch {
      mc = !1;
    }
  var Ce = null, vc = null, Mn = null;
  function So() {
    if (Mn) return Mn;
    var t, l = vc, e = l.length, a, u = "value" in Ce ? Ce.value : Ce.textContent, n = u.length;
    for (t = 0; t < e && l[t] === u[t]; t++) ;
    var i = e - t;
    for (a = 1; a <= i && l[e - a] === u[n - a]; a++) ;
    return Mn = u.slice(t, 1 < a ? 1 - a : void 0);
  }
  function Cn(t) {
    var l = t.keyCode;
    return "charCode" in t ? (t = t.charCode, t === 0 && l === 13 && (t = 13)) : t = l, t === 10 && (t = 13), 32 <= t || t === 13 ? t : 0;
  }
  function Rn() {
    return !0;
  }
  function po() {
    return !1;
  }
  function ol(t) {
    function l(e, a, u, n, i) {
      this._reactName = e, this._targetInst = u, this.type = a, this.nativeEvent = n, this.target = i, this.currentTarget = null;
      for (var c in t)
        t.hasOwnProperty(c) && (e = t[c], this[c] = e ? e(n) : n[c]);
      return this.isDefaultPrevented = (n.defaultPrevented != null ? n.defaultPrevented : n.returnValue === !1) ? Rn : po, this.isPropagationStopped = po, this;
    }
    return ut(l.prototype, {
      preventDefault: function() {
        this.defaultPrevented = !0;
        var e = this.nativeEvent;
        e && (e.preventDefault ? e.preventDefault() : typeof e.returnValue != "unknown" && (e.returnValue = !1), this.isDefaultPrevented = Rn);
      },
      stopPropagation: function() {
        var e = this.nativeEvent;
        e && (e.stopPropagation ? e.stopPropagation() : typeof e.cancelBubble != "unknown" && (e.cancelBubble = !0), this.isPropagationStopped = Rn);
      },
      persist: function() {
      },
      isPersistent: Rn
    }), l;
  }
  var Re = {
    eventPhase: 0,
    bubbles: 0,
    cancelable: 0,
    timeStamp: function(t) {
      return t.timeStamp || Date.now();
    },
    defaultPrevented: 0,
    isTrusted: 0
  }, Dn = ol(Re), Eu = ut({}, Re, { view: 0, detail: 0 }), uv = ol(Eu), hc, yc, Nu, Un = ut({}, Eu, {
    screenX: 0,
    screenY: 0,
    clientX: 0,
    clientY: 0,
    pageX: 0,
    pageY: 0,
    ctrlKey: 0,
    shiftKey: 0,
    altKey: 0,
    metaKey: 0,
    getModifierState: bc,
    button: 0,
    buttons: 0,
    relatedTarget: function(t) {
      return t.relatedTarget === void 0 ? t.fromElement === t.srcElement ? t.toElement : t.fromElement : t.relatedTarget;
    },
    movementX: function(t) {
      return "movementX" in t ? t.movementX : (t !== Nu && (Nu && t.type === "mousemove" ? (hc = t.screenX - Nu.screenX, yc = t.screenY - Nu.screenY) : yc = hc = 0, Nu = t), hc);
    },
    movementY: function(t) {
      return "movementY" in t ? t.movementY : yc;
    }
  }), _o = ol(Un), nv = ut({}, Un, { dataTransfer: 0 }), iv = ol(nv), cv = ut({}, Eu, { relatedTarget: 0 }), gc = ol(cv), fv = ut({}, Re, {
    animationName: 0,
    elapsedTime: 0,
    pseudoElement: 0
  }), sv = ol(fv), ov = ut({}, Re, {
    clipboardData: function(t) {
      return "clipboardData" in t ? t.clipboardData : window.clipboardData;
    }
  }), rv = ol(ov), dv = ut({}, Re, { data: 0 }), To = ol(dv), mv = {
    Esc: "Escape",
    Spacebar: " ",
    Left: "ArrowLeft",
    Up: "ArrowUp",
    Right: "ArrowRight",
    Down: "ArrowDown",
    Del: "Delete",
    Win: "OS",
    Menu: "ContextMenu",
    Apps: "ContextMenu",
    Scroll: "ScrollLock",
    MozPrintableKey: "Unidentified"
  }, vv = {
    8: "Backspace",
    9: "Tab",
    12: "Clear",
    13: "Enter",
    16: "Shift",
    17: "Control",
    18: "Alt",
    19: "Pause",
    20: "CapsLock",
    27: "Escape",
    32: " ",
    33: "PageUp",
    34: "PageDown",
    35: "End",
    36: "Home",
    37: "ArrowLeft",
    38: "ArrowUp",
    39: "ArrowRight",
    40: "ArrowDown",
    45: "Insert",
    46: "Delete",
    112: "F1",
    113: "F2",
    114: "F3",
    115: "F4",
    116: "F5",
    117: "F6",
    118: "F7",
    119: "F8",
    120: "F9",
    121: "F10",
    122: "F11",
    123: "F12",
    144: "NumLock",
    145: "ScrollLock",
    224: "Meta"
  }, hv = {
    Alt: "altKey",
    Control: "ctrlKey",
    Meta: "metaKey",
    Shift: "shiftKey"
  };
  function yv(t) {
    var l = this.nativeEvent;
    return l.getModifierState ? l.getModifierState(t) : (t = hv[t]) ? !!l[t] : !1;
  }
  function bc() {
    return yv;
  }
  var gv = ut({}, Eu, {
    key: function(t) {
      if (t.key) {
        var l = mv[t.key] || t.key;
        if (l !== "Unidentified") return l;
      }
      return t.type === "keypress" ? (t = Cn(t), t === 13 ? "Enter" : String.fromCharCode(t)) : t.type === "keydown" || t.type === "keyup" ? vv[t.keyCode] || "Unidentified" : "";
    },
    code: 0,
    location: 0,
    ctrlKey: 0,
    shiftKey: 0,
    altKey: 0,
    metaKey: 0,
    repeat: 0,
    locale: 0,
    getModifierState: bc,
    charCode: function(t) {
      return t.type === "keypress" ? Cn(t) : 0;
    },
    keyCode: function(t) {
      return t.type === "keydown" || t.type === "keyup" ? t.keyCode : 0;
    },
    which: function(t) {
      return t.type === "keypress" ? Cn(t) : t.type === "keydown" || t.type === "keyup" ? t.keyCode : 0;
    }
  }), bv = ol(gv), Sv = ut({}, Un, {
    pointerId: 0,
    width: 0,
    height: 0,
    pressure: 0,
    tangentialPressure: 0,
    tiltX: 0,
    tiltY: 0,
    twist: 0,
    pointerType: 0,
    isPrimary: 0
  }), xo = ol(Sv), pv = ut({}, Re, { submitter: 0 }), _v = ol(pv), Tv = ut({}, Eu, {
    touches: 0,
    targetTouches: 0,
    changedTouches: 0,
    altKey: 0,
    metaKey: 0,
    ctrlKey: 0,
    shiftKey: 0,
    getModifierState: bc
  }), xv = ol(Tv), Ev = ut({}, Re, {
    propertyName: 0,
    elapsedTime: 0,
    pseudoElement: 0
  }), Nv = ol(Ev), zv = ut({}, Un, {
    deltaX: function(t) {
      return "deltaX" in t ? t.deltaX : "wheelDeltaX" in t ? -t.wheelDeltaX : 0;
    },
    deltaY: function(t) {
      return "deltaY" in t ? t.deltaY : "wheelDeltaY" in t ? -t.wheelDeltaY : "wheelDelta" in t ? -t.wheelDelta : 0;
    },
    deltaZ: 0,
    deltaMode: 0
  }), Ov = ol(zv), Av = ut({}, Re, {
    newState: 0,
    oldState: 0,
    source: 0
  }), Mv = ol(Av), Cv = [9, 13, 27, 32], Sc = me && "CompositionEvent" in window, zu = null;
  me && "documentMode" in document && (zu = document.documentMode);
  var Rv = me && "TextEvent" in window && !zu, Eo = me && (!Sc || zu && 8 < zu && 11 >= zu), No = " ", zo = !1;
  function Oo(t, l) {
    switch (t) {
      case "keyup":
        return Cv.indexOf(l.keyCode) !== -1;
      case "keydown":
        return l.keyCode !== 229;
      case "keypress":
      case "mousedown":
      case "focusout":
        return !0;
      default:
        return !1;
    }
  }
  function Ao(t) {
    return t = t.detail, typeof t == "object" && "data" in t ? t.data : null;
  }
  var Ha = !1;
  function Dv(t, l) {
    switch (t) {
      case "compositionend":
        return Ao(l);
      case "keypress":
        return l.which !== 32 ? null : (zo = !0, No);
      case "textInput":
        return t = l.data, t === No && zo ? null : t;
      default:
        return null;
    }
  }
  function Uv(t, l) {
    if (Ha)
      return t === "compositionend" || !Sc && Oo(t, l) ? (t = So(), Mn = vc = Ce = null, Ha = !1, t) : null;
    switch (t) {
      case "paste":
        return null;
      case "keypress":
        if (!(l.ctrlKey || l.altKey || l.metaKey) || l.ctrlKey && l.altKey) {
          if (l.char && 1 < l.char.length)
            return l.char;
          if (l.which) return String.fromCharCode(l.which);
        }
        return null;
      case "compositionend":
        return Eo && l.locale !== "ko" ? null : l.data;
      default:
        return null;
    }
  }
  var jv = {
    color: !0,
    date: !0,
    datetime: !0,
    "datetime-local": !0,
    email: !0,
    month: !0,
    number: !0,
    password: !0,
    range: !0,
    search: !0,
    tel: !0,
    text: !0,
    time: !0,
    url: !0,
    week: !0
  };
  function Mo(t) {
    var l = t && t.nodeName && t.nodeName.toLowerCase();
    return l === "input" ? !!jv[t.type] : l === "textarea";
  }
  function Co(t, l, e, a) {
    Ua ? ja ? ja.push(a) : ja = [a] : Ua = a, l = ji(l, "onChange"), 0 < l.length && (e = new Dn(
      "onChange",
      "change",
      null,
      e,
      a
    ), t.push({ event: e, listeners: l }));
  }
  var Ou = null, Au = null;
  function Hv(t) {
    gm(t, 0);
  }
  function jn(t) {
    var l = _u(t);
    if (oo(l)) return t;
  }
  function Ro(t, l) {
    if (t === "change") return l;
  }
  var Do = !1;
  if (me) {
    var pc;
    if (me) {
      var _c = "oninput" in document;
      if (!_c) {
        var Uo = document.createElement("div");
        Uo.setAttribute("oninput", "return;"), _c = typeof Uo.oninput == "function";
      }
      pc = _c;
    } else pc = !1;
    Do = pc && (!document.documentMode || 9 < document.documentMode);
  }
  function jo() {
    Ou && (Ou.detachEvent("onpropertychange", Ho), Au = Ou = null);
  }
  function Ho(t) {
    if (t.propertyName === "value" && jn(Au)) {
      var l = [];
      Co(
        l,
        Au,
        t,
        rc(t)
      ), bo(Hv, l);
    }
  }
  function Bv(t, l, e) {
    t === "focusin" ? (jo(), Ou = l, Au = e, Ou.attachEvent("onpropertychange", Ho)) : t === "focusout" && jo();
  }
  function qv(t) {
    if (t === "selectionchange" || t === "keyup" || t === "keydown")
      return jn(Au);
  }
  function Yv(t, l) {
    if (t === "click") return jn(l);
  }
  function Xv(t, l) {
    if (t === "input" || t === "change")
      return jn(l);
  }
  function Gv(t, l) {
    return t === l && (t !== 0 || 1 / t === 1 / l) || t !== t && l !== l;
  }
  var El = typeof Object.is == "function" ? Object.is : Gv;
  function Mu(t, l) {
    if (El(t, l)) return !0;
    if (typeof t != "object" || t === null || typeof l != "object" || l === null)
      return !1;
    var e = Object.keys(t), a = Object.keys(l);
    if (e.length !== a.length) return !1;
    for (a = 0; a < e.length; a++) {
      var u = e[a];
      if (!tc.call(l, u) || !El(t[u], l[u]))
        return !1;
    }
    return !0;
  }
  function Tc(t) {
    if (t = t || (typeof document < "u" ? document : void 0), typeof t > "u") return null;
    try {
      return t.activeElement || t.body;
    } catch {
      return t.body;
    }
  }
  function Bo(t) {
    for (; t && t.firstChild; ) t = t.firstChild;
    return t;
  }
  function qo(t, l) {
    var e = Bo(t);
    t = 0;
    for (var a; e; ) {
      if (e.nodeType === 3) {
        if (a = t + e.textContent.length, t <= l && a >= l)
          return { node: e, offset: l - t };
        t = a;
      }
      t: {
        for (; e; ) {
          if (e.nextSibling) {
            e = e.nextSibling;
            break t;
          }
          e = e.parentNode;
        }
        e = void 0;
      }
      e = Bo(e);
    }
  }
  function Yo(t, l) {
    return t && l ? t === l ? !0 : t && t.nodeType === 3 ? !1 : l && l.nodeType === 3 ? Yo(t, l.parentNode) : "contains" in t ? t.contains(l) : t.compareDocumentPosition ? !!(t.compareDocumentPosition(l) & 16) : !1 : !1;
  }
  function Xo(t) {
    t = t != null && t.ownerDocument != null && t.ownerDocument.defaultView != null ? t.ownerDocument.defaultView : window;
    for (var l = Tc(t.document); l instanceof t.HTMLIFrameElement; ) {
      try {
        var e = typeof l.contentWindow.location.href == "string";
      } catch {
        e = !1;
      }
      if (e) t = l.contentWindow;
      else break;
      l = Tc(t.document);
    }
    return l;
  }
  function xc(t) {
    var l = t && t.nodeName && t.nodeName.toLowerCase();
    return l && (l === "input" && (t.type === "text" || t.type === "search" || t.type === "tel" || t.type === "url" || t.type === "password") || l === "textarea" || t.contentEditable === "true");
  }
  var Qv = me && "documentMode" in document && 11 >= document.documentMode, Ba = null, Ec = null, Cu = null, Nc = !1;
  function Go(t, l, e) {
    var a = e.window === e ? e.document : e.nodeType === 9 ? e : e.ownerDocument;
    Nc || Ba == null || Ba !== Tc(a) || (a = Ba, "selectionStart" in a && xc(a) ? a = { start: a.selectionStart, end: a.selectionEnd } : (a = (a.ownerDocument && a.ownerDocument.defaultView || window).getSelection(), a = {
      anchorNode: a.anchorNode,
      anchorOffset: a.anchorOffset,
      focusNode: a.focusNode,
      focusOffset: a.focusOffset
    }), Cu && Mu(Cu, a) || (Cu = a, a = ji(Ec, "onSelect"), 0 < a.length && (l = new Dn(
      "onSelect",
      "select",
      null,
      l,
      e
    ), t.push({ event: l, listeners: a }), l.target = Ba)));
  }
  function na(t, l) {
    var e = {};
    return e[t.toLowerCase()] = l.toLowerCase(), e["Webkit" + t] = "webkit" + l, e["Moz" + t] = "moz" + l, e;
  }
  var qa = {
    animationend: na("Animation", "AnimationEnd"),
    animationiteration: na("Animation", "AnimationIteration"),
    animationstart: na("Animation", "AnimationStart"),
    transitionrun: na("Transition", "TransitionRun"),
    transitionstart: na("Transition", "TransitionStart"),
    transitioncancel: na("Transition", "TransitionCancel"),
    transitionend: na("Transition", "TransitionEnd")
  }, zc = {}, Qo = {};
  me && (Qo = document.createElement("div").style, "AnimationEvent" in window || (delete qa.animationend.animation, delete qa.animationiteration.animation, delete qa.animationstart.animation), "TransitionEvent" in window || delete qa.transitionend.transition);
  function ia(t) {
    if (zc[t]) return zc[t];
    if (!qa[t]) return t;
    var l = qa[t], e;
    for (e in l)
      if (l.hasOwnProperty(e) && e in Qo)
        return zc[t] = l[e];
    return t;
  }
  var Lo = ia("animationend"), Zo = ia("animationiteration"), wo = ia("animationstart"), Lv = ia("transitionrun"), Zv = ia("transitionstart"), wv = ia("transitioncancel"), Vo = ia("transitionend"), Ko = /* @__PURE__ */ new Map(), Oc = "abort auxClick beforeToggle cancel canPlay canPlayThrough click close contextMenu copy cut drag dragEnd dragEnter dragExit dragLeave dragOver dragStart drop durationChange emptied encrypted ended error fullscreenChange fullscreenError gotPointerCapture input invalid keyDown keyPress keyUp load loadedData loadedMetadata loadStart lostPointerCapture mouseDown mouseMove mouseOut mouseOver mouseUp paste pause play playing pointerCancel pointerDown pointerMove pointerOut pointerOver pointerUp progress rateChange reset resize seeked seeking stalled submit suspend timeUpdate touchCancel touchEnd touchStart volumeChange scroll toggle touchMove waiting wheel".split(
    " "
  );
  Oc.push("scrollEnd");
  function Vl(t, l) {
    Ko.set(t, l), ua(l, [t]);
  }
  var Vv = 0;
  function ve(t, l) {
    if (t.name != null && t.name !== "auto") return t.name;
    if (l.autoName !== null) return l.autoName;
    t = $l.identifierPrefix;
    var e = Vv++;
    return t = "_" + t + "t_" + e.toString(32) + "_", l.autoName = t;
  }
  function Jo(t) {
    if (t == null || typeof t == "string")
      return t;
    var l = null, e = au;
    if (e !== null)
      for (var a = 0; a < e.length; a++) {
        var u = t[e[a]];
        if (u != null) {
          if (u === "none") return "none";
          l = l == null ? u : l + (" " + u);
        }
      }
    return l ?? t.default;
  }
  function he(t, l) {
    return t = Jo(t), l = Jo(l), l == null ? t === "auto" ? null : t : l === "auto" ? null : l;
  }
  var Hn = typeof reportError == "function" ? reportError : function(t) {
    if (typeof window == "object" && typeof window.ErrorEvent == "function") {
      var l = new window.ErrorEvent("error", {
        bubbles: !0,
        cancelable: !0,
        message: typeof t == "object" && t !== null && typeof t.message == "string" ? String(t.message) : String(t),
        error: t
      });
      if (!window.dispatchEvent(l)) return;
    } else if (typeof process == "object" && typeof process.emit == "function") {
      process.emit("uncaughtException", t);
      return;
    }
    console.error(t);
  }, jl = [], Ya = 0, Ac = 0;
  function Bn() {
    for (var t = Ya, l = Ac = Ya = 0; l < t; ) {
      var e = jl[l];
      jl[l++] = null;
      var a = jl[l];
      jl[l++] = null;
      var u = jl[l];
      jl[l++] = null;
      var n = jl[l];
      if (jl[l++] = null, a !== null && u !== null) {
        var i = a.pending;
        i === null ? u.next = u : (u.next = i.next, i.next = u), a.pending = u;
      }
      n !== 0 && ko(e, u, n);
    }
  }
  function qn(t, l, e, a) {
    jl[Ya++] = t, jl[Ya++] = l, jl[Ya++] = e, jl[Ya++] = a, Ac |= a, t.lanes |= a, t = t.alternate, t !== null && (t.lanes |= a);
  }
  function Mc(t, l, e, a) {
    return qn(t, l, e, a), Yn(t);
  }
  function ca(t, l) {
    return qn(t, null, null, l), Yn(t);
  }
  function ko(t, l, e) {
    t.lanes |= e;
    var a = t.alternate;
    a !== null && (a.lanes |= e);
    for (var u = !1, n = t.return; n !== null; )
      n.childLanes |= e, a = n.alternate, a !== null && (a.childLanes |= e), n.tag === 22 && (t = n.stateNode, t === null || t._visibility & 1 || (u = !0)), t = n, n = n.return;
    return t.tag === 3 ? (n = t.stateNode, u && l !== null && (u = 31 - Tl(e), t = n.hiddenUpdates, a = t[u], a === null ? t[u] = [l] : a.push(l), l.lane = e | 536870912), n) : null;
  }
  function Yn(t) {
    if (50 < Iu)
      throw Iu = 0, Oi = null, Error(r(185));
    for (var l = t.return; l !== null; )
      t = l, l = t.return;
    return t.tag === 3 ? t.stateNode : null;
  }
  var Xa = {};
  function Kv(t, l, e, a) {
    this.tag = t, this.key = e, this.sibling = this.child = this.return = this.stateNode = this.type = this.elementType = null, this.index = 0, this.refCleanup = this.ref = null, this.pendingProps = l, this.dependencies = this.memoizedState = this.updateQueue = this.memoizedProps = null, this.mode = a, this.subtreeFlags = this.flags = 0, this.deletions = null, this.childLanes = this.lanes = 0, this.alternate = null;
  }
  function hl(t, l, e, a) {
    return new Kv(t, l, e, a);
  }
  function Cc(t) {
    return t = t.prototype, !(!t || !t.isReactComponent);
  }
  function ye(t, l) {
    var e = t.alternate;
    return e === null ? (e = hl(
      t.tag,
      l,
      t.key,
      t.mode
    ), e.elementType = t.elementType, e.type = t.type, e.stateNode = t.stateNode, e.alternate = t, t.alternate = e) : (e.pendingProps = l, e.type = t.type, e.flags = 0, e.subtreeFlags = 0, e.deletions = null), e.flags = t.flags & 1206910976, e.childLanes = t.childLanes, e.lanes = t.lanes, e.child = t.child, e.memoizedProps = t.memoizedProps, e.memoizedState = t.memoizedState, e.updateQueue = t.updateQueue, l = t.dependencies, e.dependencies = l === null ? null : { lanes: l.lanes, firstContext: l.firstContext }, e.sibling = t.sibling, e.index = t.index, e.ref = t.ref, e.refCleanup = t.refCleanup, e;
  }
  function $o(t, l) {
    t.flags &= 1206910978;
    var e = t.alternate;
    return e === null ? (t.childLanes = 0, t.lanes = l, t.child = null, t.subtreeFlags = 0, t.memoizedProps = null, t.memoizedState = null, t.updateQueue = null, t.dependencies = null, t.stateNode = null) : (t.childLanes = e.childLanes, t.lanes = e.lanes, t.child = e.child, t.subtreeFlags = 0, t.deletions = null, t.memoizedProps = e.memoizedProps, t.memoizedState = e.memoizedState, t.updateQueue = e.updateQueue, t.type = e.type, l = e.dependencies, t.dependencies = l === null ? null : {
      lanes: l.lanes,
      firstContext: l.firstContext
    }), t;
  }
  function Xn(t, l, e, a, u, n) {
    var i = 0;
    if (a = t, typeof a == "function") Cc(a) && (i = 1);
    else if (typeof a == "string")
      i = py(
        t,
        e,
        Il.current
      ) ? 26 : t === "html" || t === "head" || t === "body" ? 27 : 5;
    else
      t: switch (a) {
        case sl:
          return t = hl(31, e, l, u), t.elementType = sl, t.lanes = n, t;
        case _t:
          return fa(e.children, u, n, l);
        case gt:
          i = 8, u |= 24;
          break;
        case qt:
          return t = hl(12, e, l, u | 2), t.elementType = qt, t.lanes = n, t;
        case W:
          return t = hl(13, e, l, u), t.elementType = W, t.lanes = n, t;
        case tt:
          return t = hl(19, e, l, u), t.elementType = tt, t.lanes = n, t;
        case Zl:
        case s:
          return t = u | 32, t = hl(30, e, l, t), t.elementType = s, t.lanes = n, t.stateNode = {
            autoName: null,
            paired: null,
            clones: null,
            ref: null
          }, t;
        default:
          if (typeof a == "object" && a !== null)
            switch (a.$$typeof) {
              case Yt:
                i = 10;
                break t;
              case cl:
                i = 9;
                break t;
              case B:
                i = 11;
                break t;
              case Tt:
                i = 14;
                break t;
              case dt:
                i = 16, a = null;
                break t;
            }
          i = 29, e = Error(
            r(130, t === null ? "null" : typeof t, "")
          ), a = null;
      }
    return l = hl(i, e, l, u), l.elementType = t, l.type = a, l.lanes = n, l;
  }
  function fa(t, l, e, a) {
    return t = hl(7, t, a, l), t.lanes = e, t;
  }
  function Rc(t, l, e) {
    return t = hl(6, t, null, l), t.lanes = e, t;
  }
  function Wo(t) {
    var l = hl(18, null, null, 0);
    return l.stateNode = t, l;
  }
  function Dc(t, l, e) {
    return l = hl(
      4,
      t.children !== null ? t.children : [],
      t.key,
      l
    ), l.lanes = e, l.stateNode = {
      containerInfo: t.containerInfo,
      pendingChildren: null,
      implementation: t.implementation
    }, l;
  }
  var Fo = /* @__PURE__ */ new WeakMap();
  function Hl(t, l) {
    if (typeof t == "object" && t !== null) {
      var e = Fo.get(t);
      return e !== void 0 ? e : (l = {
        value: t,
        source: l,
        stack: ws(l)
      }, Fo.set(t, l), l);
    }
    return {
      value: t,
      source: l,
      stack: ws(l)
    };
  }
  var Ga = [], Qa = 0, Gn = null, Ru = 0, Bl = [], ql = 0, De = null, te = 1, le = "";
  function ge(t, l) {
    Ga[Qa++] = Ru, Ga[Qa++] = Gn, Gn = t, Ru = l;
  }
  function Io(t, l, e) {
    Bl[ql++] = te, Bl[ql++] = le, Bl[ql++] = De, De = t;
    var a = te;
    t = le;
    var u = 32 - Tl(a) - 1;
    a &= ~(1 << u), e += 1;
    var n = 32 - Tl(l) + u;
    if (30 < n) {
      var i = u - u % 5;
      n = (a & (1 << i) - 1).toString(32), a >>= i, u -= i, te = 1 << 32 - Tl(l) + u | e << u | a, le = n + t;
    } else
      te = 1 << n | e << u | a, le = t;
  }
  function Qn(t) {
    t.return !== null && (ge(t, 1), Io(t, 1, 0));
  }
  function Uc(t) {
    for (; t === Gn; )
      Gn = Ga[--Qa], Ga[Qa] = null, Ru = Ga[--Qa], Ga[Qa] = null;
    for (; t === De; )
      De = Bl[--ql], Bl[ql] = null, le = Bl[--ql], Bl[ql] = null, te = Bl[--ql], Bl[ql] = null;
  }
  function Po(t, l) {
    Bl[ql++] = te, Bl[ql++] = le, Bl[ql++] = De, te = l.id, le = l.overflow, De = t;
  }
  var Wt = null, Rt = null, ct = !1, Ue = null, Yl = !1, jc = Error(r(519));
  function je(t) {
    var l = Error(
      r(
        418,
        1 < arguments.length && arguments[1] !== void 0 && arguments[1] ? "text" : "HTML",
        ""
      )
    );
    throw Du(Hl(l, t)), jc;
  }
  function tr(t) {
    var l = t.stateNode, e = t.type, a = t.memoizedProps;
    switch (l[tl] = t, l[vl] = a, e) {
      case "dialog":
        st("cancel", l), st("close", l);
        break;
      case "iframe":
      case "object":
      case "embed":
        st("load", l);
        break;
      case "video":
      case "audio":
        for (e = 0; e < tn.length; e++)
          st(tn[e], l);
        break;
      case "source":
        st("error", l);
        break;
      case "img":
      case "image":
      case "link":
        st("error", l), st("load", l);
        break;
      case "details":
        st("toggle", l);
        break;
      case "input":
        st("invalid", l), ro(
          l,
          a.value,
          a.defaultValue,
          a.checked,
          a.defaultChecked,
          a.type,
          a.name,
          !0
        );
        break;
      case "select":
        st("invalid", l);
        break;
      case "textarea":
        st("invalid", l), vo(l, a.value, a.defaultValue, a.children);
    }
    e = a.children, typeof e != "string" && typeof e != "number" && typeof e != "bigint" || l.textContent === "" + e || a.suppressHydrationWarning === !0 || _m(l.textContent, e) ? (a.popover != null && (st("beforetoggle", l), st("toggle", l)), a.onScroll != null && st("scroll", l), a.onScrollEnd != null && st("scrollend", l), a.onClick != null && (l.onclick = Pl), l = !0) : l = !1, l || je(t, !0);
  }
  function Ln(t) {
    for (Wt = t.return; Wt; )
      switch (Wt.tag) {
        case 5:
        case 31:
        case 13:
          Yl = !1;
          return;
        case 27:
        case 3:
          Yl = !0;
          return;
        default:
          Wt = Wt.return;
      }
  }
  function La(t) {
    if (t !== Wt) return !1;
    if (!ct) return Ln(t), ct = !0, !1;
    var l = t.tag, e;
    if ((e = l !== 3 && l !== 27) && ((e = l === 5) && (e = t.type, e = !(e !== "form" && e !== "button") || rs(t.type, t.memoizedProps)), e = !e), e && Rt && je(t), Ln(t), l === 13) {
      if (t = t.memoizedState, t = t !== null ? t.dehydrated : null, !t) throw Error(r(317));
      Rt = Gm(t);
    } else if (l === 31) {
      if (t = t.memoizedState, t = t !== null ? t.dehydrated : null, !t) throw Error(r(317));
      Rt = Gm(t);
    } else
      l === 27 ? (l = Rt, We(t.type) ? (t = ps, ps = null, Rt = t) : Rt = l) : Rt = Wt ? Gl(t.stateNode.nextSibling) : null;
    return !0;
  }
  function sa() {
    Rt = Wt = null, ct = !1;
  }
  function Hc() {
    var t = Ue;
    return t !== null && (bl === null ? bl = t : bl.push.apply(
      bl,
      t
    ), Ue = null), t;
  }
  function Du(t) {
    Ue === null ? Ue = [t] : Ue.push(t);
  }
  var Bc = Dl(null), oa = null, be = null;
  function He(t, l, e) {
    Ct(Bc, l._currentValue), l._currentValue = e;
  }
  function Se(t) {
    t._currentValue = Bc.current, Qt(Bc);
  }
  function Zn(t, l, e) {
    for (; t !== null; ) {
      var a = t.alternate;
      if ((t.childLanes & l) !== l ? (t.childLanes |= l, a !== null && (a.childLanes |= l)) : a !== null && (a.childLanes & l) !== l && (a.childLanes |= l), t === e) break;
      t = t.return;
    }
  }
  function qc(t, l, e, a) {
    var u = t.child;
    for (u !== null && (u.return = t); u !== null; ) {
      var n = u.dependencies;
      if (n !== null) {
        var i = u.child;
        n = n.firstContext;
        t: for (; n !== null; ) {
          var c = n;
          n = u;
          for (var f = 0; f < l.length; f++)
            if (c.context === l[f]) {
              n.lanes |= e, c = n.alternate, c !== null && (c.lanes |= e), Zn(
                n.return,
                e,
                t
              ), a || (i = null);
              break t;
            }
          n = c.next;
        }
      } else if (u.tag === 18) {
        if (i = u.return, i === null) throw Error(r(341));
        i.lanes |= e, n = i.alternate, n !== null && (n.lanes |= e), Zn(i, e, t), i = null;
      } else
        u.tag === 13 && u.memoizedState !== null && u.memoizedState.dehydrated === null ? (u.lanes |= e, i = u.alternate, i !== null && (i.lanes |= e), Zn(
          u.return,
          e,
          t
        ), i = u.child, i = i !== null ? i.sibling : null) : i = u.child;
      if (i !== null) i.return = u;
      else
        for (i = u; i !== null; ) {
          if (i === t) {
            i = null;
            break;
          }
          if (u = i.sibling, u !== null) {
            u.return = i.return, i = u;
            break;
          }
          i = i.return;
        }
      u = i;
    }
  }
  function ra(t, l, e, a) {
    t = null;
    for (var u = l, n = !1; u !== null; ) {
      if (!n) {
        if ((u.flags & 524288) !== 0) n = !0;
        else if ((u.flags & 262144) !== 0) break;
      }
      if (u.tag === 10) {
        var i = u.alternate;
        if (i === null) throw Error(r(387));
        if (i = i.memoizedProps, i !== null) {
          var c = u.type;
          El(u.pendingProps.value, i.value) || (t !== null ? t.push(c) : t = [c]);
        }
      } else if (u === yn.current) {
        if (i = u.alternate, i === null) throw Error(r(387));
        i.memoizedState.memoizedState !== u.memoizedState.memoizedState && (t !== null ? t.push(mu) : t = [mu]);
      }
      u = u.return;
    }
    return t !== null && qc(
      l,
      t,
      e,
      a
    ), l.flags |= 262144, t !== null;
  }
  function wn(t) {
    for (t = t.firstContext; t !== null; ) {
      if (!El(
        t.context._currentValue,
        t.memoizedValue
      ))
        return !0;
      t = t.next;
    }
    return !1;
  }
  function da(t) {
    oa = t, be = null, t = t.dependencies, t !== null && (t.firstContext = null);
  }
  function ll(t) {
    return lr(oa, t);
  }
  function Vn(t, l) {
    return oa === null && da(t), lr(t, l);
  }
  function lr(t, l) {
    var e = l._currentValue;
    if (l = { context: l, memoizedValue: e, next: null }, be === null) {
      if (t === null) throw Error(r(308));
      be = l, t.dependencies = { lanes: 0, firstContext: l }, t.flags |= 524288;
    } else be = be.next = l;
    return e;
  }
  var Jv = typeof AbortController < "u" ? AbortController : function() {
    var t = [], l = this.signal = {
      aborted: !1,
      addEventListener: function(e, a) {
        t.push(a);
      }
    };
    this.abort = function() {
      l.aborted = !0, t.forEach(function(e) {
        return e();
      });
    };
  }, kv = o.unstable_scheduleCallback, $v = o.unstable_NormalPriority, Zt = {
    $$typeof: Yt,
    Consumer: null,
    Provider: null,
    _currentValue: null,
    _currentValue2: null,
    _threadCount: 0
  };
  function Yc() {
    return {
      controller: new Jv(),
      data: /* @__PURE__ */ new Map(),
      refCount: 0
    };
  }
  function Uu(t) {
    t.refCount--, t.refCount === 0 && kv($v, function() {
      t.controller.abort();
    });
  }
  function er(t, l) {
    if ((t.pendingLanes & 4194048) !== 0) {
      var e = t.transitionTypes;
      for (e === null && (e = t.transitionTypes = []), t = 0; t < l.length; t++) {
        var a = l[t];
        e.indexOf(a) === -1 && e.push(a);
      }
    }
  }
  var ju = null;
  function Wv(t) {
    var l = t.transitionTypes;
    return t.transitionTypes = null, l;
  }
  var Hu = null, Xc = 0, ma = 0, Za = null;
  function Fv(t, l) {
    if (Hu === null) {
      var e = Hu = [];
      Xc = 0, ma = es(), Za = {
        status: "pending",
        value: void 0,
        then: function(a) {
          e.push(a);
        }
      };
    }
    return Xc++, l.then(ar, ar), l;
  }
  function ar() {
    if (--Xc === 0 && (ju = null, Hu !== null)) {
      Za !== null && (Za.status = "fulfilled");
      var t = Hu;
      Hu = null, ma = 0, Za = null;
      for (var l = 0; l < t.length; l++) (0, t[l])();
    }
  }
  function Iv(t, l) {
    var e = [], a = {
      status: "pending",
      value: null,
      reason: null,
      then: function(u) {
        e.push(u);
      }
    };
    return t.then(
      function() {
        a.status = "fulfilled", a.value = l;
        for (var u = 0; u < e.length; u++) (0, e[u])(l);
      },
      function(u) {
        for (a.status = "rejected", a.reason = u, u = 0; u < e.length; u++)
          (0, e[u])(void 0);
      }
    ), a;
  }
  var ur = H.S;
  H.S = function(t, l) {
    if (Wd = pl(), typeof l == "object" && l !== null && typeof l.then == "function" && Fv(t, l), ju !== null)
      for (var e = cu; e !== null; )
        er(e, ju), e = e.next;
    if (e = t.types, e !== null) {
      for (var a = cu; a !== null; )
        er(a, e), a = a.next;
      if (ma !== 0) {
        a = ju, a === null && (a = ju = []);
        for (var u = 0; u < e.length; u++) {
          var n = e[u];
          a.indexOf(n) === -1 && a.push(n);
        }
      }
    }
    ur !== null && ur(t, l);
  };
  var va = Dl(null);
  function Gc() {
    var t = va.current;
    return t !== null ? t : At.pooledCache;
  }
  function Kn(t, l) {
    l === null ? Ct(va, va.current) : Ct(va, l.pool);
  }
  function nr() {
    var t = Gc();
    return t === null ? null : { parent: Zt._currentValue, pool: t };
  }
  var wa = Error(r(460)), Qc = Error(r(474)), Jn = Error(r(542)), kn = { then: function() {
  } };
  function ir(t) {
    return t = t.status, t === "fulfilled" || t === "rejected";
  }
  function cr(t, l, e) {
    switch (e = t[e], e === void 0 ? t.push(l) : e !== l && (l.then(Pl, Pl), l = e), l.status) {
      case "fulfilled":
        return l.value;
      case "rejected":
        throw t = l.reason, sr(t), t === void 0 && !("reason" in l) ? Error(r(600)) : t;
      default:
        if (typeof l.status == "string") l.then(Pl, Pl);
        else {
          if (t = At, t !== null && 100 < t.shellSuspendCounter)
            throw Error(r(482));
          t = l, t.status = "pending", t.then(
            function(a) {
              if (l.status === "pending") {
                var u = l;
                u.status = "fulfilled", u.value = a;
              }
            },
            function(a) {
              if (l.status === "pending") {
                var u = l;
                u.status = "rejected", u.reason = a;
              }
            }
          );
        }
        switch (l.status) {
          case "fulfilled":
            return l.value;
          case "rejected":
            throw t = l.reason, sr(t), t;
        }
        throw ya = l, wa;
    }
  }
  function ha(t) {
    try {
      var l = t._init;
      return l(t._payload);
    } catch (e) {
      throw e !== null && typeof e == "object" && typeof e.then == "function" ? (ya = e, wa) : e;
    }
  }
  var ya = null;
  function fr() {
    if (ya === null) throw Error(r(459));
    var t = ya;
    return ya = null, t;
  }
  function sr(t) {
    if (t === wa || t === Jn)
      throw Error(r(483));
  }
  var Va = null, Bu = 0;
  function $n(t) {
    var l = Bu;
    return Bu += 1, Va === null && (Va = []), cr(Va, t, l);
  }
  function Be(t, l) {
    l = l.props.ref, t.ref = l !== void 0 ? l : null;
  }
  function Wn(t, l) {
    throw l.$$typeof === lt ? Error(r(525)) : (t = Object.prototype.toString.call(l), Error(
      r(
        31,
        t === "[object Object]" ? "object with keys {" + Object.keys(l).join(", ") + "}" : t
      )
    ));
  }
  function or(t) {
    function l(h, d) {
      if (t) {
        var g = h.deletions;
        g === null ? (h.deletions = [d], h.flags |= 16) : g.push(d);
      }
    }
    function e(h, d) {
      if (!t) return null;
      for (; d !== null; )
        l(h, d), d = d.sibling;
      return null;
    }
    function a(h) {
      for (var d = /* @__PURE__ */ new Map(); h !== null; )
        h.key === null ? d.set(h.index, h) : d.set(h.key, h), h = h.sibling;
      return d;
    }
    function u(h, d) {
      return h = ye(h, d), h.index = 0, h.sibling = null, h;
    }
    function n(h, d, g) {
      return h.index = g, t ? (g = h.alternate, g !== null ? (g = g.index, g < d ? (h.flags |= 2, d) : g) : (h.flags |= 134217730, d)) : (h.flags |= 1048576, d);
    }
    function i(h) {
      return t && h.alternate === null && (h.flags |= 134217730), h;
    }
    function c(h, d, g, N) {
      return d === null || d.tag !== 6 ? (d = Rc(g, h.mode, N), d.return = h, d) : (d = u(d, g), d.return = h, d);
    }
    function f(h, d, g, N) {
      var Q = g.type;
      return Q === _t ? (h = S(
        h,
        d,
        g.props.children,
        N,
        g.key
      ), Be(h, g), h) : d !== null && (d.elementType === Q || typeof Q == "object" && Q !== null && Q.$$typeof === dt && ha(Q) === d.type) ? (d = u(d, g.props), Be(d, g), d.return = h, d) : (d = Xn(
        g.type,
        g.key,
        g.props,
        null,
        h.mode,
        N
      ), Be(d, g), d.return = h, d);
    }
    function y(h, d, g, N) {
      return d === null || d.tag !== 4 || d.stateNode.containerInfo !== g.containerInfo || d.stateNode.implementation !== g.implementation ? (d = Dc(g, h.mode, N), d.return = h, d) : (d = u(d, g.children || []), d.return = h, d);
    }
    function S(h, d, g, N, Q) {
      return d === null || d.tag !== 7 ? (d = fa(
        g,
        h.mode,
        N,
        Q
      ), d.return = h, d) : (d = u(d, g), d.return = h, d);
    }
    function z(h, d, g) {
      if (typeof d == "string" && d !== "" || typeof d == "number" || typeof d == "bigint")
        return d = Rc(
          "" + d,
          h.mode,
          g
        ), d.return = h, d;
      if (typeof d == "object" && d !== null) {
        switch (d.$$typeof) {
          case Ht:
            return g = Xn(
              d.type,
              d.key,
              d.props,
              null,
              h.mode,
              g
            ), Be(g, d), g.return = h, g;
          case $:
            return d = Dc(
              d,
              h.mode,
              g
            ), d.return = h, d;
          case dt:
            return d = ha(d), z(h, d, g);
        }
        if (I(d) || D(d))
          return d = fa(
            d,
            h.mode,
            g,
            null
          ), d.return = h, d;
        if (typeof d.then == "function")
          return z(h, $n(d), g);
        if (d.$$typeof === Yt)
          return z(
            h,
            Vn(h, d),
            g
          );
        Wn(h, d);
      }
      return null;
    }
    function v(h, d, g, N) {
      var Q = d !== null ? d.key : null;
      if (typeof g == "string" && g !== "" || typeof g == "number" || typeof g == "bigint")
        return Q !== null ? null : c(h, d, "" + g, N);
      if (typeof g == "object" && g !== null) {
        switch (g.$$typeof) {
          case Ht:
            return g.key === Q ? f(h, d, g, N) : null;
          case $:
            return g.key === Q ? y(h, d, g, N) : null;
          case dt:
            return g = ha(g), v(h, d, g, N);
        }
        if (I(g) || D(g))
          return Q !== null ? null : S(h, d, g, N, null);
        if (typeof g.then == "function")
          return v(
            h,
            d,
            $n(g),
            N
          );
        if (g.$$typeof === Yt)
          return v(
            h,
            d,
            Vn(h, g),
            N
          );
        Wn(h, g);
      }
      return null;
    }
    function b(h, d, g, N, Q) {
      if (typeof N == "string" && N !== "" || typeof N == "number" || typeof N == "bigint")
        return h = h.get(g) || null, c(d, h, "" + N, Q);
      if (typeof N == "object" && N !== null) {
        switch (N.$$typeof) {
          case Ht:
            return h = h.get(
              N.key === null ? g : N.key
            ) || null, f(d, h, N, Q);
          case $:
            return h = h.get(
              N.key === null ? g : N.key
            ) || null, y(d, h, N, Q);
          case dt:
            return N = ha(N), b(
              h,
              d,
              g,
              N,
              Q
            );
        }
        if (I(N) || D(N))
          return h = h.get(g) || null, S(d, h, N, Q, null);
        if (typeof N.then == "function")
          return b(
            h,
            d,
            g,
            $n(N),
            Q
          );
        if (N.$$typeof === Yt)
          return b(
            h,
            d,
            g,
            Vn(d, N),
            Q
          );
        Wn(d, N);
      }
      return null;
    }
    function j(h, d, g, N) {
      for (var Q = null, rt = null, K = d, P = d = 0, Kt = null; K !== null && P < g.length; P++) {
        K.index > P ? (Kt = K, K = null) : Kt = K.sibling;
        var mt = v(
          h,
          K,
          g[P],
          N
        );
        if (mt === null) {
          K === null && (K = Kt);
          break;
        }
        t && K && mt.alternate === null && l(h, K), d = n(mt, d, P), rt === null ? Q = mt : rt.sibling = mt, rt = mt, K = Kt;
      }
      if (P === g.length)
        return e(h, K), ct && ge(h, P), Q;
      if (K === null) {
        for (; P < g.length; P++)
          K = z(h, g[P], N), K !== null && (d = n(
            K,
            d,
            P
          ), rt === null ? Q = K : rt.sibling = K, rt = K);
        return ct && ge(h, P), Q;
      }
      for (K = a(K); P < g.length; P++)
        Kt = b(
          K,
          h,
          P,
          g[P],
          N
        ), Kt !== null && (t && (mt = Kt.alternate, mt !== null && K.delete(mt.key === null ? P : mt.key)), d = n(
          Kt,
          d,
          P
        ), rt === null ? Q = Kt : rt.sibling = Kt, rt = Kt);
      return t && K.forEach(function(la) {
        return l(h, la);
      }), ct && ge(h, P), Q;
    }
    function Z(h, d, g, N) {
      if (g == null) throw Error(r(151));
      for (var Q = null, rt = null, K = d, P = d = 0, Kt = null, mt = g.next(); K !== null && !mt.done; P++, mt = g.next()) {
        K.index > P ? (Kt = K, K = null) : Kt = K.sibling;
        var la = v(h, K, mt.value, N);
        if (la === null) {
          K === null && (K = Kt);
          break;
        }
        t && K && la.alternate === null && l(h, K), d = n(la, d, P), rt === null ? Q = la : rt.sibling = la, rt = la, K = Kt;
      }
      if (mt.done)
        return e(h, K), ct && ge(h, P), Q;
      if (K === null) {
        for (; !mt.done; P++, mt = g.next())
          mt = z(h, mt.value, N), mt !== null && (d = n(mt, d, P), rt === null ? Q = mt : rt.sibling = mt, rt = mt);
        return ct && ge(h, P), Q;
      }
      for (K = a(K); !mt.done; P++, mt = g.next())
        mt = b(K, h, P, mt.value, N), mt !== null && (t && (Kt = mt.alternate, Kt !== null && K.delete(
          Kt.key === null ? P : Kt.key
        )), d = n(mt, d, P), rt === null ? Q = mt : rt.sibling = mt, rt = mt);
      return t && K.forEach(function(Dy) {
        return l(h, Dy);
      }), ct && ge(h, P), Q;
    }
    function it(h, d, g, N) {
      if (typeof g == "object" && g !== null && g.type === _t && g.key === null && g.props.ref === void 0 && (g = g.props.children), typeof g == "object" && g !== null) {
        switch (g.$$typeof) {
          case Ht:
            t: {
              for (var Q = g.key; d !== null; ) {
                if (d.key === Q) {
                  if (Q = g.type, Q === _t) {
                    if (d.tag === 7) {
                      e(
                        h,
                        d.sibling
                      ), N = u(
                        d,
                        g.props.children
                      ), Be(N, g), N.return = h, h = N;
                      break t;
                    }
                  } else if (d.elementType === Q || typeof Q == "object" && Q !== null && Q.$$typeof === dt && ha(Q) === d.type) {
                    e(
                      h,
                      d.sibling
                    ), N = u(d, g.props), Be(N, g), N.return = h, h = N;
                    break t;
                  }
                  e(h, d);
                  break;
                } else l(h, d);
                d = d.sibling;
              }
              g.type === _t ? (N = fa(
                g.props.children,
                h.mode,
                N,
                g.key
              ), Be(N, g), N.return = h, h = N) : (N = Xn(
                g.type,
                g.key,
                g.props,
                null,
                h.mode,
                N
              ), Be(N, g), N.return = h, h = N);
            }
            return i(h);
          case $:
            t: {
              for (Q = g.key; d !== null; ) {
                if (d.key === Q)
                  if (d.tag === 4 && d.stateNode.containerInfo === g.containerInfo && d.stateNode.implementation === g.implementation) {
                    e(
                      h,
                      d.sibling
                    ), N = u(d, g.children || []), N.return = h, h = N;
                    break t;
                  } else {
                    e(h, d);
                    break;
                  }
                else l(h, d);
                d = d.sibling;
              }
              N = Dc(g, h.mode, N), N.return = h, h = N;
            }
            return i(h);
          case dt:
            return g = ha(g), it(
              h,
              d,
              g,
              N
            );
        }
        if (I(g))
          return j(
            h,
            d,
            g,
            N
          );
        if (D(g)) {
          if (Q = D(g), typeof Q != "function") throw Error(r(150));
          return g = Q.call(g), Z(
            h,
            d,
            g,
            N
          );
        }
        if (typeof g.then == "function")
          return it(
            h,
            d,
            $n(g),
            N
          );
        if (g.$$typeof === Yt)
          return it(
            h,
            d,
            Vn(h, g),
            N
          );
        Wn(h, g);
      }
      return typeof g == "string" && g !== "" || typeof g == "number" || typeof g == "bigint" ? (g = "" + g, d !== null && d.tag === 6 ? (e(h, d.sibling), N = u(d, g), N.return = h, h = N) : (e(h, d), N = Rc(g, h.mode, N), N.return = h, h = N), i(h)) : e(h, d);
    }
    return function(h, d, g, N) {
      try {
        Bu = 0;
        var Q = it(
          h,
          d,
          g,
          N
        );
        return Va = null, Q;
      } catch (K) {
        if (K === wa || K === Jn) throw K;
        var rt = hl(29, K, null, h.mode);
        return rt.lanes = N, rt.return = h, rt;
      }
    };
  }
  var ga = or(!0), rr = or(!1), qe = !1;
  function Lc(t) {
    t.updateQueue = {
      baseState: t.memoizedState,
      firstBaseUpdate: null,
      lastBaseUpdate: null,
      shared: { pending: null, lanes: 0, hiddenCallbacks: null },
      callbacks: null
    };
  }
  function Zc(t, l) {
    t = t.updateQueue, l.updateQueue === t && (l.updateQueue = {
      baseState: t.baseState,
      firstBaseUpdate: t.firstBaseUpdate,
      lastBaseUpdate: t.lastBaseUpdate,
      shared: t.shared,
      callbacks: null
    });
  }
  function Ye(t) {
    return { lane: t, tag: 0, payload: null, callback: null, next: null };
  }
  function Xe(t, l, e) {
    var a = t.updateQueue;
    if (a === null) return null;
    if (a = a.shared, (yt & 2) !== 0) {
      var u = a.pending;
      return u === null ? l.next = l : (l.next = u.next, u.next = l), a.pending = l, l = Yn(t), ko(t, null, e), l;
    }
    return qn(t, a, l, e), Yn(t);
  }
  function qu(t, l, e) {
    if (l = l.updateQueue, l !== null && (l = l.shared, (e & 4194048) !== 0)) {
      var a = l.lanes;
      a &= t.pendingLanes, e |= a, l.lanes = e, Fs(t, e);
    }
  }
  function wc(t, l) {
    var e = t.updateQueue, a = t.alternate;
    if (a !== null && (a = a.updateQueue, e === a)) {
      var u = null, n = null;
      if (e = e.firstBaseUpdate, e !== null) {
        do {
          var i = {
            lane: e.lane,
            tag: e.tag,
            payload: e.payload,
            callback: null,
            next: null
          };
          n === null ? u = n = i : n = n.next = i, e = e.next;
        } while (e !== null);
        n === null ? u = n = l : n = n.next = l;
      } else u = n = l;
      e = {
        baseState: a.baseState,
        firstBaseUpdate: u,
        lastBaseUpdate: n,
        shared: a.shared,
        callbacks: a.callbacks
      }, t.updateQueue = e;
      return;
    }
    t = e.lastBaseUpdate, t === null ? e.firstBaseUpdate = l : t.next = l, e.lastBaseUpdate = l;
  }
  var Vc = !1;
  function Yu() {
    if (Vc) {
      var t = Za;
      if (t !== null) throw t;
    }
  }
  function Xu(t, l, e, a) {
    Vc = !1;
    var u = t.updateQueue;
    qe = !1;
    var n = u.firstBaseUpdate, i = u.lastBaseUpdate, c = u.shared.pending;
    if (c !== null) {
      u.shared.pending = null;
      var f = c, y = f.next;
      f.next = null, i === null ? n = y : i.next = y, i = f;
      var S = t.alternate;
      S !== null && (S = S.updateQueue, c = S.lastBaseUpdate, c !== i && (c === null ? S.firstBaseUpdate = y : c.next = y, S.lastBaseUpdate = f));
    }
    if (n !== null) {
      var z = u.baseState;
      i = 0, S = y = f = null, c = n;
      do {
        var v = c.lane & -536870913, b = v !== c.lane;
        if (b ? (ot & v) === v : (a & v) === v) {
          v !== 0 && v === ma && (Vc = !0), S !== null && (S = S.next = {
            lane: 0,
            tag: c.tag,
            payload: c.payload,
            callback: null,
            next: null
          });
          t: {
            var j = t, Z = c;
            v = l;
            var it = e;
            switch (Z.tag) {
              case 1:
                if (j = Z.payload, typeof j == "function") {
                  z = j.call(it, z, v);
                  break t;
                }
                z = j;
                break t;
              case 3:
                j.flags = j.flags & -65537 | 128;
              case 0:
                if (j = Z.payload, v = typeof j == "function" ? j.call(it, z, v) : j, v == null) break t;
                z = ut({}, z, v);
                break t;
              case 2:
                qe = !0;
            }
          }
          v = c.callback, v !== null && (t.flags |= 64, b && (t.flags |= 8192), b = u.callbacks, b === null ? u.callbacks = [v] : b.push(v));
        } else
          b = {
            lane: v,
            tag: c.tag,
            payload: c.payload,
            callback: c.callback,
            next: null
          }, S === null ? (y = S = b, f = z) : S = S.next = b, i |= v;
        if (c = c.next, c === null) {
          if (c = u.shared.pending, c === null)
            break;
          b = c, c = b.next, b.next = null, u.lastBaseUpdate = b, u.shared.pending = null;
        }
      } while (!0);
      S === null && (f = z), u.baseState = f, u.firstBaseUpdate = y, u.lastBaseUpdate = S, n === null && (u.shared.lanes = 0), Ke |= i, t.lanes = i, t.memoizedState = z;
    }
  }
  function dr(t, l) {
    if (typeof t != "function")
      throw Error(r(191, t));
    t.call(l);
  }
  function mr(t, l) {
    var e = t.callbacks;
    if (e !== null)
      for (t.callbacks = null, t = 0; t < e.length; t++)
        dr(e[t], l);
  }
  var Ge = Dl(null), Fn = Dl(0);
  function vr(t, l) {
    t = Ee, Ct(Fn, t), Ct(Ge, l), Ee = t | l.baseLanes;
  }
  function Kc() {
    Ct(Fn, Ee), Ct(Ge, Ge.current);
  }
  function Jc() {
    Ee = Fn.current, Qt(Ge), Qt(Fn);
  }
  var el = Dl(null), fl = null;
  function Qe(t) {
    var l = t.alternate;
    Ct(al, al.current & 1), Ct(el, t), fl === null && (l === null || Ge.current !== null || l.memoizedState !== null) && (fl = t);
  }
  function kc(t) {
    Ct(al, al.current), Ct(el, t), fl === null && (fl = t);
  }
  function hr(t) {
    t.tag === 22 ? (Ct(al, al.current), Ct(el, t), fl === null && (fl = t)) : Le();
  }
  function Le() {
    Ct(al, al.current), Ct(el, el.current);
  }
  function Nl(t) {
    Qt(el), fl === t && (fl = null), Qt(al);
  }
  var al = Dl(0);
  function Gu(t, l) {
    Ct(el, el.current), Ct(al, l);
  }
  function $c(t) {
    Qt(al), Qt(el), fl === t && (fl = null);
  }
  function In(t) {
    for (var l = t; l !== null; ) {
      if (l.tag === 13) {
        var e = l.memoizedState;
        if (e !== null && (e = e.dehydrated, e === null || bs(e) || Ss(e)))
          return l;
      } else if (l.tag === 19 && l.memoizedProps.revealOrder !== "independent") {
        if ((l.flags & 128) !== 0) return l;
      } else if (l.child !== null) {
        l.child.return = l, l = l.child;
        continue;
      }
      if (l === t) break;
      for (; l.sibling === null; ) {
        if (l.return === null || l.return === t) return null;
        l = l.return;
      }
      l.sibling.return = l.return, l = l.sibling;
    }
    return null;
  }
  var pe = 0, nt = null, zt = null, wt = null, Pn = !1, Ka = !1, ba = !1, ti = 0, Qu = 0, Ja = null, Pv = 0;
  function Xt() {
    throw Error(r(321));
  }
  function Wc(t, l) {
    if (l === null) return !1;
    for (var e = 0; e < l.length && e < t.length; e++)
      if (!El(t[e], l[e])) return !1;
    return !0;
  }
  function Fc(t, l, e, a, u, n) {
    return pe = n, nt = l, l.memoizedState = null, l.updateQueue = null, l.lanes = 0, H.H = t === null || t.memoizedState === null ? Ir : Pr, ba = !1, n = e(a, u), ba = !1, Ka && (n = gr(
      l,
      e,
      a,
      u
    )), yr(t), n;
  }
  function yr(t) {
    H.H = ci;
    var l = zt !== null && zt.next !== null;
    if (pe = 0, wt = zt = nt = null, Pn = !1, Qu = 0, Ja = null, l) throw Error(r(300));
    t === null || Vt || (t = t.dependencies, t !== null && wn(t) && (Vt = !0));
  }
  function gr(t, l, e, a) {
    nt = t;
    var u = 0;
    do {
      if (Ka && (Ja = null), Qu = 0, Ka = !1, 25 <= u) throw Error(r(301));
      if (u += 1, wt = zt = null, t.updateQueue != null) {
        var n = t.updateQueue;
        n.lastEffect = null, n.events = null, n.stores = null, n.memoCache != null && (n.memoCache.index = 0);
      }
      H.H = ch, n = l(e, a);
    } while (Ka);
    return n;
  }
  function th() {
    var t = H.H, l = t.useState()[0];
    return l = typeof l.then == "function" ? Lu(l) : l, t = t.useState()[0], (zt !== null ? zt.memoizedState : null) !== t && (nt.flags |= 1024), l;
  }
  function Ic() {
    var t = ti !== 0;
    return ti = 0, t;
  }
  function Pc(t, l, e) {
    l.updateQueue = t.updateQueue, l.flags &= -2053, t.lanes &= ~e;
  }
  function tf(t) {
    if (Pn) {
      for (t = t.memoizedState; t !== null; ) {
        var l = t.queue;
        l !== null && (l.pending = null), t = t.next;
      }
      Pn = !1;
    }
    pe = 0, wt = zt = nt = null, Ka = !1, Qu = ti = 0, Ja = null;
  }
  function rl() {
    var t = {
      memoizedState: null,
      baseState: null,
      baseQueue: null,
      queue: null,
      next: null
    };
    return wt === null ? nt.memoizedState = wt = t : wt = wt.next = t, wt;
  }
  function Lt() {
    if (zt === null) {
      var t = nt.alternate;
      t = t !== null ? t.memoizedState : null;
    } else t = zt.next;
    var l = wt === null ? nt.memoizedState : wt.next;
    if (l !== null)
      wt = l, zt = t;
    else {
      if (t === null)
        throw nt.alternate === null ? Error(r(467)) : Error(r(310));
      zt = t, t = {
        memoizedState: zt.memoizedState,
        baseState: zt.baseState,
        baseQueue: zt.baseQueue,
        queue: zt.queue,
        next: null
      }, wt === null ? nt.memoizedState = wt = t : wt = wt.next = t;
    }
    return wt;
  }
  function li() {
    return { lastEffect: null, events: null, stores: null, memoCache: null };
  }
  function Lu(t) {
    var l = Qu;
    return Qu += 1, Ja === null && (Ja = []), t = cr(Ja, t, l), l = nt, (wt === null ? l.memoizedState : wt.next) === null && (l = l.alternate, H.H = l === null || l.memoizedState === null ? Ir : Pr), t;
  }
  function ei(t) {
    if (t !== null && typeof t == "object") {
      if (typeof t.then == "function") return Lu(t);
      if (t.$$typeof === T) return;
      if (t.$$typeof === Yt) return ll(t);
    }
    throw Error(r(438, String(t)));
  }
  function lf(t) {
    var l = null, e = nt.updateQueue;
    if (e !== null && (l = e.memoCache), l == null) {
      var a = nt.alternate;
      a !== null && (a = a.updateQueue, a !== null && (a = a.memoCache, a != null && (l = {
        data: a.data.map(function(u) {
          return u.slice();
        }),
        index: 0
      })));
    }
    if (l == null && (l = { data: [], index: 0 }), e === null && (e = li(), nt.updateQueue = e), e.memoCache = l, e = l.data[l.index], e === void 0)
      for (e = l.data[l.index] = Array(t), a = 0; a < t; a++)
        e[a] = x;
    return l.index++, e;
  }
  function _e(t, l) {
    return typeof l == "function" ? l(t) : l;
  }
  function ai(t) {
    var l = Lt();
    return ef(l, zt, t);
  }
  function ef(t, l, e) {
    var a = t.queue;
    if (a === null) throw Error(r(311));
    a.lastRenderedReducer = e;
    var u = t.baseQueue, n = a.pending;
    if (n !== null) {
      if (u !== null) {
        var i = u.next;
        u.next = n.next, n.next = i;
      }
      l.baseQueue = u = n, a.pending = null;
    }
    if (n = t.baseState, u === null) t.memoizedState = n;
    else {
      l = u.next;
      var c = i = null, f = null, y = l, S = !1;
      do {
        var z = y.lane & -536870913;
        if (z !== y.lane ? (ot & z) === z : (pe & z) === z) {
          var v = y.revertLane;
          if (v === 0)
            f !== null && (f = f.next = {
              lane: 0,
              revertLane: 0,
              gesture: null,
              action: y.action,
              hasEagerState: y.hasEagerState,
              eagerState: y.eagerState,
              next: null
            }), z === ma && (S = !0);
          else if ((pe & v) === v) {
            y = y.next, v === ma && (S = !0);
            continue;
          } else
            z = {
              lane: 0,
              revertLane: y.revertLane,
              gesture: null,
              action: y.action,
              hasEagerState: y.hasEagerState,
              eagerState: y.eagerState,
              next: null
            }, f === null ? (c = f = z, i = n) : f = f.next = z, nt.lanes |= v, Ke |= v;
          z = y.action, ba && e(n, z), n = y.hasEagerState ? y.eagerState : e(n, z);
        } else
          v = {
            lane: z,
            revertLane: y.revertLane,
            gesture: y.gesture,
            action: y.action,
            hasEagerState: y.hasEagerState,
            eagerState: y.eagerState,
            next: null
          }, f === null ? (c = f = v, i = n) : f = f.next = v, nt.lanes |= z, Ke |= z;
        y = y.next;
      } while (y !== null && y !== l);
      if (f === null ? i = n : f.next = c, !El(n, t.memoizedState) && (Vt = !0, S && (e = Za, e !== null)))
        throw e;
      t.memoizedState = n, t.baseState = i, t.baseQueue = f, a.lastRenderedState = n;
    }
    return u === null && (a.lanes = 0), [t.memoizedState, a.dispatch];
  }
  function af(t) {
    var l = Lt(), e = l.queue;
    if (e === null) throw Error(r(311));
    e.lastRenderedReducer = t;
    var a = e.dispatch, u = e.pending, n = l.memoizedState;
    if (u !== null) {
      e.pending = null;
      var i = u = u.next;
      do
        n = t(n, i.action), i = i.next;
      while (i !== u);
      El(n, l.memoizedState) || (Vt = !0), l.memoizedState = n, l.baseQueue === null && (l.baseState = n), e.lastRenderedState = n;
    }
    return [n, a];
  }
  function br(t, l, e) {
    var a = nt, u = Lt(), n = ct;
    if (n) {
      if (e === void 0) throw Error(r(407));
      e = e();
    } else e = l();
    var i = !El(
      (zt || u).memoizedState,
      e
    );
    if (i && (u.memoizedState = e, Vt = !0), u = u.queue, cf(_r.bind(null, a, u, t), [
      t
    ]), t = u.getSnapshot !== l || i || wt !== null && (wt.memoizedState.tag & 1) !== 0, ka(
      t ? 9 : 8,
      { destroy: void 0 },
      pr.bind(null, a, u, e, l),
      null
    ), t) {
      if (a.flags |= 2048, At === null) throw Error(r(349));
      n || (pe & 127) !== 0 || Sr(a, l, e);
    }
    return e;
  }
  function Sr(t, l, e) {
    t.flags |= 16384, t = { getSnapshot: l, value: e }, l = nt.updateQueue, l === null ? (l = li(), nt.updateQueue = l, l.stores = [t]) : (e = l.stores, e === null ? l.stores = [t] : e.push(t));
  }
  function pr(t, l, e, a) {
    l.value = e, l.getSnapshot = a, Tr(l) && xr(t);
  }
  function _r(t, l, e) {
    return e(function() {
      Tr(l) && xr(t);
    });
  }
  function Tr(t) {
    var l = t.getSnapshot;
    t = t.value;
    try {
      var e = l();
      return !El(t, e);
    } catch {
      return !0;
    }
  }
  function xr(t) {
    var l = ca(t, 2);
    l !== null && Sl(l, t, 2);
  }
  function uf(t) {
    var l = rl();
    if (typeof t == "function") {
      var e = t;
      if (t = e(), ba) {
        Me(!0);
        try {
          e();
        } finally {
          Me(!1);
        }
      }
    }
    return l.memoizedState = l.baseState = t, l.queue = {
      pending: null,
      lanes: 0,
      dispatch: null,
      lastRenderedReducer: _e,
      lastRenderedState: t
    }, l;
  }
  function Er(t, l, e, a) {
    return t.baseState = e, ef(
      t,
      zt,
      typeof a == "function" ? a : _e
    );
  }
  function lh(t, l, e, a, u) {
    if (ii(t)) throw Error(r(485));
    if (t = l.action, t !== null) {
      var n = {
        payload: u,
        action: t,
        next: null,
        isTransition: !0,
        status: "pending",
        value: null,
        reason: null,
        listeners: [],
        then: function(i) {
          n.listeners.push(i);
        }
      };
      H.T !== null ? e(!0) : n.isTransition = !1, a(n), e = l.pending, e === null ? (n.next = l.pending = n, Nr(l, n)) : (n.next = e.next, l.pending = e.next = n);
    }
  }
  function Nr(t, l) {
    var e = l.action, a = l.payload, u = t.state;
    if (l.isTransition) {
      var n = H.T, i = {};
      i.types = n !== null ? n.types : null, H.T = i;
      try {
        var c = e(u, a), f = H.S;
        f !== null && f(i, c), zr(t, l, c);
      } catch (y) {
        nf(t, l, y);
      } finally {
        n !== null && i.types !== null && (n.types = i.types), H.T = n;
      }
    } else
      try {
        n = e(u, a), zr(t, l, n);
      } catch (y) {
        nf(t, l, y);
      }
  }
  function zr(t, l, e) {
    e !== null && typeof e == "object" && typeof e.then == "function" ? e.then(
      function(a) {
        Or(t, l, a);
      },
      function(a) {
        return nf(t, l, a);
      }
    ) : Or(t, l, e);
  }
  function Or(t, l, e) {
    l.status = "fulfilled", l.value = e, Ar(l), t.state = e, l = t.pending, l !== null && (e = l.next, e === l ? t.pending = null : (e = e.next, l.next = e, Nr(t, e)));
  }
  function nf(t, l, e) {
    var a = t.pending;
    if (t.pending = null, a !== null) {
      a = a.next;
      do
        l.status = "rejected", l.reason = e, Ar(l), l = l.next;
      while (l !== a);
    }
    t.action = null;
  }
  function Ar(t) {
    t = t.listeners;
    for (var l = 0; l < t.length; l++) (0, t[l])();
  }
  function Mr(t, l) {
    return l;
  }
  function Cr(t, l) {
    if (ct) {
      var e = At.formState;
      if (e !== null) {
        t: {
          var a = nt;
          if (ct) {
            if (Rt) {
              l: {
                for (var u = Rt, n = Yl; u.nodeType !== 8; ) {
                  if (!n) {
                    u = null;
                    break l;
                  }
                  if (u = Gl(
                    u.nextSibling
                  ), u === null) {
                    u = null;
                    break l;
                  }
                }
                n = u.data, u = n === "F!" || n === "F" ? u : null;
              }
              if (u) {
                Rt = Gl(
                  u.nextSibling
                ), a = u.data === "F!";
                break t;
              }
            }
            je(a);
          }
          a = !1;
        }
        a && (l = e[0]);
      }
    }
    return e = rl(), e.memoizedState = e.baseState = l, a = {
      pending: null,
      lanes: 0,
      dispatch: null,
      lastRenderedReducer: Mr,
      lastRenderedState: l
    }, e.queue = a, e = $r.bind(
      null,
      nt,
      a
    ), a.dispatch = e, a = uf(!1), n = df.bind(
      null,
      nt,
      !1,
      a.queue
    ), a = rl(), u = {
      state: l,
      dispatch: null,
      action: t,
      pending: null
    }, a.queue = u, e = lh.bind(
      null,
      nt,
      u,
      n,
      e
    ), u.dispatch = e, a.memoizedState = t, [l, e, !1];
  }
  function Rr(t) {
    var l = Lt();
    return Dr(l, zt, t);
  }
  function Dr(t, l, e) {
    if (l = ef(
      t,
      l,
      Mr
    )[0], t = ai(_e)[0], typeof l == "object" && l !== null && typeof l.then == "function")
      try {
        var a = Lu(l);
      } catch (i) {
        throw i === wa ? Jn : i;
      }
    else a = l;
    l = Lt();
    var u = l.queue, n = u.dispatch;
    return e !== l.memoizedState && (nt.flags |= 2048, ka(
      9,
      { destroy: void 0 },
      eh.bind(null, u, e),
      null
    )), [a, n, t];
  }
  function eh(t, l) {
    t.action = l;
  }
  function Ur(t) {
    var l = Lt(), e = zt;
    if (e !== null)
      return Dr(l, e, t);
    Lt(), l = l.memoizedState, e = Lt();
    var a = e.queue.dispatch;
    return e.memoizedState = t, [l, a, !1];
  }
  function ka(t, l, e, a) {
    return t = { tag: t, create: e, deps: a, inst: l, next: null }, l = nt.updateQueue, l === null && (l = li(), nt.updateQueue = l), e = l.lastEffect, e === null ? l.lastEffect = t.next = t : (a = e.next, e.next = t, t.next = a, l.lastEffect = t), t;
  }
  function jr() {
    return Lt().memoizedState;
  }
  function ui(t, l, e, a) {
    var u = rl();
    nt.flags |= t, u.memoizedState = ka(
      1 | l,
      { destroy: void 0 },
      e,
      a === void 0 ? null : a
    );
  }
  function ni(t, l, e, a) {
    var u = Lt();
    a = a === void 0 ? null : a;
    var n = u.memoizedState.inst;
    zt !== null && a !== null && Wc(a, zt.memoizedState.deps) ? u.memoizedState = ka(l, n, e, a) : (nt.flags |= t, u.memoizedState = ka(
      1 | l,
      n,
      e,
      a
    ));
  }
  function Hr(t, l) {
    ui(8390656, 8, t, l);
  }
  function cf(t, l) {
    ni(2048, 8, t, l);
  }
  function ah(t) {
    nt.flags |= 4;
    var l = nt.updateQueue;
    if (l === null)
      l = li(), nt.updateQueue = l, l.events = [t];
    else {
      var e = l.events;
      e === null ? l.events = [t] : e.push(t);
    }
  }
  function Br(t) {
    var l = Lt().memoizedState;
    return ah({ ref: l, nextImpl: t }), function() {
      if ((yt & 2) !== 0) throw Error(r(440));
      return l.impl.apply(void 0, arguments);
    };
  }
  function qr(t, l) {
    return ni(4, 2, t, l);
  }
  function Yr(t, l) {
    return ni(4, 4, t, l);
  }
  function Xr(t, l) {
    if (typeof l == "function") {
      t = t();
      var e = l(t);
      return function() {
        typeof e == "function" ? e() : l(null);
      };
    }
    if (l != null)
      return t = t(), l.current = t, function() {
        l.current = null;
      };
  }
  function Gr(t, l, e) {
    e = e != null ? e.concat([t]) : null, ni(4, 4, Xr.bind(null, l, t), e);
  }
  function ff() {
  }
  function Qr(t, l) {
    var e = Lt();
    l = l === void 0 ? null : l;
    var a = e.memoizedState;
    return l !== null && Wc(l, a[1]) ? a[0] : (e.memoizedState = [t, l], t);
  }
  function Lr(t, l) {
    var e = Lt();
    l = l === void 0 ? null : l;
    var a = e.memoizedState;
    if (l !== null && Wc(l, a[1]))
      return a[0];
    if (a = t(), ba) {
      Me(!0);
      try {
        t();
      } finally {
        Me(!1);
      }
    }
    return e.memoizedState = [a, l], a;
  }
  function sf(t, l, e) {
    return e === void 0 || (pe & 1073741824) !== 0 && (ot & 261930) === 0 ? t.memoizedState = l : (t.memoizedState = e, t = Id(), nt.lanes |= t, Ke |= t, e);
  }
  function Zr(t, l, e, a) {
    return El(e, l) ? e : Ge.current !== null ? (t = sf(t, e, a), El(t, l) || (Vt = !0), t) : (pe & 106) === 0 || (pe & 1073741824) !== 0 && (ot & 261930) === 0 ? (Vt = !0, t.memoizedState = e) : (t = Id(), nt.lanes |= t, Ke |= t, l);
  }
  function wr(t, l, e, a, u) {
    var n = V.p;
    V.p = n !== 0 && 8 > n ? n : 8;
    var i = H.T, c = {};
    c.types = i !== null ? i.types : null, H.T = c, df(t, !1, l, e);
    try {
      var f = u(), y = H.S;
      if (y !== null && y(c, f), f !== null && typeof f == "object" && typeof f.then == "function") {
        var S = Iv(
          f,
          a
        );
        Zu(
          t,
          l,
          S,
          Ml(t)
        );
      } else
        Zu(
          t,
          l,
          a,
          Ml(t)
        );
    } catch (z) {
      Zu(
        t,
        l,
        { then: function() {
        }, status: "rejected", reason: z },
        Ml()
      );
    } finally {
      V.p = n, i !== null && c.types !== null && (i.types = c.types), H.T = i;
    }
  }
  function uh() {
  }
  function of(t, l, e, a) {
    if (t.tag !== 5) throw Error(r(476));
    var u = Vr(t).queue;
    wr(
      t,
      u,
      l,
      Ut,
      e === null ? uh : function() {
        return Kr(t), e(a);
      }
    );
  }
  function Vr(t) {
    var l = t.memoizedState;
    if (l !== null) return l;
    l = {
      memoizedState: Ut,
      baseState: Ut,
      baseQueue: null,
      queue: {
        pending: null,
        lanes: 0,
        dispatch: null,
        lastRenderedReducer: _e,
        lastRenderedState: Ut
      },
      next: null
    };
    var e = {};
    return l.next = {
      memoizedState: e,
      baseState: e,
      baseQueue: null,
      queue: {
        pending: null,
        lanes: 0,
        dispatch: null,
        lastRenderedReducer: _e,
        lastRenderedState: e
      },
      next: null
    }, t.memoizedState = l, t = t.alternate, t !== null && (t.memoizedState = l), l;
  }
  function Kr(t) {
    var l = Vr(t);
    l.next === null && (l = t.alternate.memoizedState), Zu(
      t,
      l.next.queue,
      {},
      Ml()
    );
  }
  function rf() {
    return ll(mu);
  }
  function Jr() {
    return Lt().memoizedState;
  }
  function kr() {
    return Lt().memoizedState;
  }
  function nh(t) {
    for (var l = t.return; l !== null; ) {
      switch (l.tag) {
        case 24:
        case 3:
          var e = Ml();
          t = Ye(e);
          var a = Xe(l, t, e);
          a !== null && (Sl(a, l, e), qu(a, l, e)), l = { cache: Yc() }, t.payload = l;
          return;
      }
      l = l.return;
    }
  }
  function ih(t, l, e) {
    var a = Ml();
    e = {
      lane: a,
      revertLane: 0,
      gesture: null,
      action: e,
      hasEagerState: !1,
      eagerState: null,
      next: null
    }, ii(t) ? Wr(l, e) : (e = Mc(t, l, e, a), e !== null && (Sl(e, t, a), Fr(e, l, a)));
  }
  function $r(t, l, e) {
    var a = Ml();
    Zu(t, l, e, a);
  }
  function Zu(t, l, e, a) {
    var u = {
      lane: a,
      revertLane: 0,
      gesture: null,
      action: e,
      hasEagerState: !1,
      eagerState: null,
      next: null
    };
    if (ii(t)) Wr(l, u);
    else {
      var n = t.alternate;
      if (t.lanes === 0 && (n === null || n.lanes === 0) && (n = l.lastRenderedReducer, n !== null))
        try {
          var i = l.lastRenderedState, c = n(i, e);
          if (u.hasEagerState = !0, u.eagerState = c, El(c, i))
            return qn(t, l, u, 0), At === null && Bn(), !1;
        } catch {
        }
      if (e = Mc(t, l, u, a), e !== null)
        return Sl(e, t, a), Fr(e, l, a), !0;
    }
    return !1;
  }
  function df(t, l, e, a) {
    if (a = {
      lane: 2,
      revertLane: es(),
      gesture: null,
      action: a,
      hasEagerState: !1,
      eagerState: null,
      next: null
    }, ii(t)) {
      if (l) throw Error(r(479));
    } else
      l = Mc(
        t,
        e,
        a,
        2
      ), l !== null && Sl(l, t, 2);
  }
  function ii(t) {
    var l = t.alternate;
    return t === nt || l !== null && l === nt;
  }
  function Wr(t, l) {
    Ka = Pn = !0;
    var e = t.pending;
    e === null ? l.next = l : (l.next = e.next, e.next = l), t.pending = l;
  }
  function Fr(t, l, e) {
    if ((e & 4194048) !== 0) {
      var a = l.lanes;
      a &= t.pendingLanes, e |= a, l.lanes = e, Fs(t, e);
    }
  }
  var ci = {
    readContext: ll,
    use: ei,
    useCallback: Xt,
    useContext: Xt,
    useEffect: Xt,
    useImperativeHandle: Xt,
    useLayoutEffect: Xt,
    useInsertionEffect: Xt,
    useMemo: Xt,
    useReducer: Xt,
    useRef: Xt,
    useState: Xt,
    useDebugValue: Xt,
    useDeferredValue: Xt,
    useTransition: Xt,
    useSyncExternalStore: Xt,
    useId: Xt,
    useHostTransitionStatus: Xt,
    useFormState: Xt,
    useActionState: Xt,
    useOptimistic: Xt,
    useMemoCache: Xt,
    useCacheRefresh: Xt,
    useEffectEvent: Xt
  }, Ir = {
    readContext: ll,
    use: ei,
    useCallback: function(t, l) {
      return rl().memoizedState = [
        t,
        l === void 0 ? null : l
      ], t;
    },
    useContext: ll,
    useEffect: Hr,
    useImperativeHandle: function(t, l, e) {
      e = e != null ? e.concat([t]) : null, ui(
        4194308,
        4,
        Xr.bind(null, l, t),
        e
      );
    },
    useLayoutEffect: function(t, l) {
      return ui(4194308, 4, t, l);
    },
    useInsertionEffect: function(t, l) {
      ui(4, 2, t, l);
    },
    useMemo: function(t, l) {
      var e = rl();
      l = l === void 0 ? null : l;
      var a = t();
      if (ba) {
        Me(!0);
        try {
          t();
        } finally {
          Me(!1);
        }
      }
      return e.memoizedState = [a, l], a;
    },
    useReducer: function(t, l, e) {
      var a = rl();
      if (e !== void 0) {
        var u = e(l);
        if (ba) {
          Me(!0);
          try {
            e(l);
          } finally {
            Me(!1);
          }
        }
      } else u = l;
      return a.memoizedState = a.baseState = u, t = {
        pending: null,
        lanes: 0,
        dispatch: null,
        lastRenderedReducer: t,
        lastRenderedState: u
      }, a.queue = t, t = t.dispatch = ih.bind(
        null,
        nt,
        t
      ), [a.memoizedState, t];
    },
    useRef: function(t) {
      var l = rl();
      return t = { current: t }, l.memoizedState = t;
    },
    useState: function(t) {
      t = uf(t);
      var l = t.queue, e = $r.bind(null, nt, l);
      return l.dispatch = e, [t.memoizedState, e];
    },
    useDebugValue: ff,
    useDeferredValue: function(t, l) {
      var e = rl();
      return sf(e, t, l);
    },
    useTransition: function() {
      var t = uf(!1);
      return t = wr.bind(
        null,
        nt,
        t.queue,
        !0,
        !1
      ), rl().memoizedState = t, [!1, t];
    },
    useSyncExternalStore: function(t, l, e) {
      var a = nt, u = rl();
      if (ct) {
        if (e === void 0)
          throw Error(r(407));
        e = e();
      } else {
        if (e = l(), At === null)
          throw Error(r(349));
        (ot & 127) !== 0 || Sr(a, l, e);
      }
      u.memoizedState = e;
      var n = { value: e, getSnapshot: l };
      return u.queue = n, Hr(_r.bind(null, a, n, t), [
        t
      ]), a.flags |= 2048, ka(
        9,
        { destroy: void 0 },
        pr.bind(
          null,
          a,
          n,
          e,
          l
        ),
        null
      ), e;
    },
    useId: function() {
      var t = rl(), l = At.identifierPrefix;
      if (ct) {
        var e = le, a = te;
        e = (a & ~(1 << 32 - Tl(a) - 1)).toString(32) + e, l = "_" + l + "R_" + e, e = ti++, 0 < e && (l += "H" + e.toString(32)), l += "_";
      } else
        e = Pv++, l = "_" + l + "r_" + e.toString(32) + "_";
      return t.memoizedState = l;
    },
    useHostTransitionStatus: rf,
    useFormState: Cr,
    useActionState: Cr,
    useOptimistic: function(t) {
      var l = rl();
      l.memoizedState = l.baseState = t;
      var e = {
        pending: null,
        lanes: 0,
        dispatch: null,
        lastRenderedReducer: null,
        lastRenderedState: null
      };
      return l.queue = e, l = df.bind(
        null,
        nt,
        !0,
        e
      ), e.dispatch = l, [t, l];
    },
    useMemoCache: lf,
    useCacheRefresh: function() {
      return rl().memoizedState = nh.bind(
        null,
        nt
      );
    },
    useEffectEvent: function(t) {
      var l = rl(), e = { impl: t };
      return l.memoizedState = e, function() {
        if ((yt & 2) !== 0)
          throw Error(r(440));
        return e.impl.apply(void 0, arguments);
      };
    }
  }, Pr = {
    readContext: ll,
    use: ei,
    useCallback: Qr,
    useContext: ll,
    useEffect: cf,
    useImperativeHandle: Gr,
    useInsertionEffect: qr,
    useLayoutEffect: Yr,
    useMemo: Lr,
    useReducer: ai,
    useRef: jr,
    useState: function() {
      return ai(_e);
    },
    useDebugValue: ff,
    useDeferredValue: function(t, l) {
      var e = Lt();
      return Zr(
        e,
        zt.memoizedState,
        t,
        l
      );
    },
    useTransition: function() {
      var t = ai(_e)[0], l = Lt().memoizedState;
      return [
        typeof t == "boolean" ? t : Lu(t),
        l
      ];
    },
    useSyncExternalStore: br,
    useId: Jr,
    useHostTransitionStatus: rf,
    useFormState: Rr,
    useActionState: Rr,
    useOptimistic: function(t, l) {
      var e = Lt();
      return Er(e, zt, t, l);
    },
    useMemoCache: lf,
    useCacheRefresh: kr,
    useEffectEvent: Br
  }, ch = {
    readContext: ll,
    use: ei,
    useCallback: Qr,
    useContext: ll,
    useEffect: cf,
    useImperativeHandle: Gr,
    useInsertionEffect: qr,
    useLayoutEffect: Yr,
    useMemo: Lr,
    useReducer: af,
    useRef: jr,
    useState: function() {
      return af(_e);
    },
    useDebugValue: ff,
    useDeferredValue: function(t, l) {
      var e = Lt();
      return zt === null ? sf(e, t, l) : Zr(
        e,
        zt.memoizedState,
        t,
        l
      );
    },
    useTransition: function() {
      var t = af(_e)[0], l = Lt().memoizedState;
      return [
        typeof t == "boolean" ? t : Lu(t),
        l
      ];
    },
    useSyncExternalStore: br,
    useId: Jr,
    useHostTransitionStatus: rf,
    useFormState: Ur,
    useActionState: Ur,
    useOptimistic: function(t, l) {
      var e = Lt();
      return zt !== null ? Er(e, zt, t, l) : (e.baseState = t, [t, e.queue.dispatch]);
    },
    useMemoCache: lf,
    useCacheRefresh: kr,
    useEffectEvent: Br
  };
  function mf(t, l, e, a) {
    l = t.memoizedState, e = e(a, l), e = e == null ? l : ut({}, l, e), t.memoizedState = e, t.lanes === 0 && (t.updateQueue.baseState = e);
  }
  var vf = {
    enqueueSetState: function(t, l, e) {
      t = t._reactInternals;
      var a = Ml(), u = Ye(a);
      u.payload = l, e != null && (u.callback = e), l = Xe(t, u, a), l !== null && (Sl(l, t, a), qu(l, t, a));
    },
    enqueueReplaceState: function(t, l, e) {
      t = t._reactInternals;
      var a = Ml(), u = Ye(a);
      u.tag = 1, u.payload = l, e != null && (u.callback = e), l = Xe(t, u, a), l !== null && (Sl(l, t, a), qu(l, t, a));
    },
    enqueueForceUpdate: function(t, l) {
      t = t._reactInternals;
      var e = Ml(), a = Ye(e);
      a.tag = 2, l != null && (a.callback = l), l = Xe(t, a, e), l !== null && (Sl(l, t, e), qu(l, t, e));
    }
  };
  function td(t, l, e, a, u, n, i) {
    return t = t.stateNode, typeof t.shouldComponentUpdate == "function" ? t.shouldComponentUpdate(a, n, i) : l.prototype && l.prototype.isPureReactComponent ? !Mu(e, a) || !Mu(u, n) : !0;
  }
  function ld(t, l, e, a) {
    t = l.state, typeof l.componentWillReceiveProps == "function" && l.componentWillReceiveProps(e, a), typeof l.UNSAFE_componentWillReceiveProps == "function" && l.UNSAFE_componentWillReceiveProps(e, a), l.state !== t && vf.enqueueReplaceState(l, l.state, null);
  }
  function Sa(t, l) {
    var e = l;
    if ("ref" in l) {
      e = {};
      for (var a in l)
        a !== "ref" && (e[a] = l[a]);
    }
    if (t = t.defaultProps) {
      e === l && (e = ut({}, e));
      for (var u in t)
        e[u] === void 0 && (e[u] = t[u]);
    }
    return e;
  }
  function ed(t) {
    Hn(t);
  }
  function ad(t) {
    console.error(t);
  }
  function ud(t) {
    Hn(t);
  }
  function fi(t, l) {
    try {
      var e = t.onUncaughtError;
      e(l.value, { componentStack: l.stack });
    } catch (a) {
      setTimeout(function() {
        throw a;
      });
    }
  }
  function nd(t, l, e) {
    try {
      var a = t.onCaughtError;
      a(e.value, {
        componentStack: e.stack,
        errorBoundary: l.tag === 1 ? l.stateNode : null
      });
    } catch (u) {
      setTimeout(function() {
        throw u;
      });
    }
  }
  function hf(t, l, e) {
    return e = Ye(e), e.tag = 3, e.payload = { element: null }, e.callback = function() {
      fi(t, l);
    }, e;
  }
  function id(t) {
    return t = Ye(t), t.tag = 3, t;
  }
  function cd(t, l, e, a) {
    var u = e.type.getDerivedStateFromError;
    if (typeof u == "function") {
      var n = a.value;
      t.payload = function() {
        return u(n);
      }, t.callback = function() {
        nd(l, e, a);
      };
    }
    var i = e.stateNode;
    i !== null && typeof i.componentDidCatch == "function" && (t.callback = function() {
      nd(l, e, a), typeof u != "function" && (Je === null ? Je = /* @__PURE__ */ new Set([this]) : Je.add(this));
      var c = a.stack;
      this.componentDidCatch(a.value, {
        componentStack: c !== null ? c : ""
      });
    });
  }
  function fh(t, l, e, a, u) {
    if (e.flags |= 32768, a !== null && typeof a == "object" && typeof a.then == "function") {
      if (l = e.alternate, l !== null && ra(
        l,
        e,
        u,
        !0
      ), e = el.current, e !== null) {
        switch (e.tag) {
          case 31:
          case 13:
          case 19:
            return fl === null ? Mi() : e.alternate === null && Gt === 0 && (Gt = 3), e.flags &= -257, e.flags |= 65536, e.lanes = u, a === kn ? e.flags |= 16384 : (l = e.updateQueue, l === null ? e.updateQueue = /* @__PURE__ */ new Set([a]) : l.add(a), Pf(t, a, u)), !1;
          case 22:
            return e.flags |= 65536, a === kn ? e.flags |= 16384 : (l = e.updateQueue, l === null ? (l = {
              transitions: null,
              markerInstances: null,
              retryQueue: /* @__PURE__ */ new Set([a])
            }, e.updateQueue = l) : (e = l.retryQueue, e === null ? l.retryQueue = /* @__PURE__ */ new Set([a]) : e.add(a)), Pf(t, a, u)), !1;
        }
        throw Error(r(435, e.tag));
      }
      return Pf(t, a, u), Mi(), !1;
    }
    if (ct)
      return l = el.current, l !== null ? ((l.flags & 65536) === 0 && (l.flags |= 256), l.flags |= 65536, l.lanes = u, a !== jc && (t = Error(r(422), { cause: a }), Du(Hl(t, e)))) : (a !== jc && (l = Error(r(423), {
        cause: a
      }), Du(
        Hl(l, e)
      )), t = t.current.alternate, t.flags |= 65536, u &= -u, t.lanes |= u, a = Hl(a, e), u = hf(
        t.stateNode,
        a,
        u
      ), wc(t, u), Gt !== 4 && (Gt = 2)), !1;
    var n = Error(r(520), { cause: a });
    if (n = Hl(n, e), Fu === null ? Fu = [n] : Fu.push(n), Gt !== 4 && (Gt = 2), l === null) return !0;
    a = Hl(a, e), e = l;
    do {
      switch (e.tag) {
        case 3:
          return e.flags |= 65536, t = u & -u, e.lanes |= t, t = hf(e.stateNode, a, t), wc(e, t), !1;
        case 1:
          if (l = e.type, n = e.stateNode, (e.flags & 128) === 0 && (typeof l.getDerivedStateFromError == "function" || n !== null && typeof n.componentDidCatch == "function" && (Je === null || !Je.has(n))))
            return e.flags |= 65536, u &= -u, e.lanes |= u, u = id(u), cd(
              u,
              t,
              e,
              a
            ), wc(e, u), !1;
          break;
        case 22:
          if (e.memoizedState !== null)
            return e.flags |= 65536, !1;
      }
      e = e.return;
    } while (e !== null);
    return !1;
  }
  var yf = Error(r(461)), Vt = !1;
  function kt(t, l, e, a) {
    l.child = t === null ? rr(l, null, e, a) : ga(
      l,
      t.child,
      e,
      a
    );
  }
  function fd(t, l, e, a, u) {
    e = e.render;
    var n = l.ref;
    if ("ref" in a) {
      var i = {};
      for (var c in a)
        c !== "ref" && (i[c] = a[c]);
    } else i = a;
    return da(l), a = Fc(
      t,
      l,
      e,
      i,
      n,
      u
    ), c = Ic(), t !== null && !Vt ? (Pc(t, l, u), Te(t, l, u)) : (ct && c && Qn(l), l.flags |= 1, kt(t, l, a, u), l.child);
  }
  function sd(t, l, e, a, u) {
    if (t === null) {
      var n = e.type;
      return typeof n == "function" && !Cc(n) && n.defaultProps === void 0 && e.compare === null ? (l.tag = 15, l.type = n, od(
        t,
        l,
        n,
        a,
        u
      )) : (t = Xn(
        e.type,
        null,
        a,
        l,
        l.mode,
        u
      ), t.ref = l.ref, t.return = l, l.child = t);
    }
    if (n = t.child, !Ef(t, u)) {
      var i = n.memoizedProps;
      if (e = e.compare, e = e !== null ? e : Mu, e(i, a) && t.ref === l.ref)
        return Te(t, l, u);
    }
    return l.flags |= 1, t = ye(n, a), t.ref = l.ref, t.return = l, l.child = t;
  }
  function od(t, l, e, a, u) {
    if (t !== null) {
      var n = t.memoizedProps;
      if (Mu(n, a) && t.ref === l.ref)
        if (Vt = !1, l.pendingProps = a = n, Ef(t, u))
          (t.flags & 131072) !== 0 && (Vt = !0);
        else
          return l.lanes = t.lanes, Te(t, l, u);
    }
    return gf(
      t,
      l,
      e,
      a,
      u
    );
  }
  function rd(t, l, e, a) {
    var u = a.children, n = t !== null ? t.memoizedState : null;
    if (t === null && l.stateNode === null && (l.stateNode = {
      _visibility: 1,
      _pendingMarkers: null,
      _retryCache: null,
      _transitions: null
    }), a.mode === "hidden") {
      if ((l.flags & 128) !== 0) {
        if (n = n !== null ? n.baseLanes | e : e, t !== null) {
          for (a = l.child = t.child, u = 0; a !== null; )
            u = u | a.lanes | a.childLanes, a = a.sibling;
          a = u & ~n;
        } else a = 0, l.child = null;
        return dd(
          t,
          l,
          n,
          e,
          a
        );
      }
      if ((e & 536870912) !== 0)
        l.memoizedState = { baseLanes: 0, cachePool: null }, t !== null && Kn(
          l,
          n !== null ? n.cachePool : null
        ), n !== null ? vr(l, n) : Kc(), hr(l);
      else
        return a = l.lanes = 536870912, dd(
          t,
          l,
          n !== null ? n.baseLanes | e : e,
          e,
          a
        );
    } else
      n !== null ? (Kn(l, n.cachePool), vr(l, n), Le(), l.memoizedState = null) : (t !== null && Kn(l, null), Kc(), Le());
    return kt(t, l, u, e), l.child;
  }
  function wu(t, l) {
    return t !== null && t.tag === 22 || l.stateNode !== null || (l.stateNode = {
      _visibility: 1,
      _pendingMarkers: null,
      _retryCache: null,
      _transitions: null
    }), l.sibling;
  }
  function dd(t, l, e, a, u) {
    var n = Gc();
    return n = n === null ? null : { parent: Zt._currentValue, pool: n }, l.memoizedState = {
      baseLanes: e,
      cachePool: n
    }, t !== null && Kn(l, null), Kc(), hr(l), t !== null && ra(t, l, a, !0), l.childLanes = u, null;
  }
  function si(t, l) {
    return l = oi(
      { mode: l.mode, children: l.children },
      t.mode
    ), l.ref = t.ref, t.child = l, l.return = t, l;
  }
  function md(t, l, e) {
    return ga(l, t.child, null, e), t = si(l, l.pendingProps), t.flags |= 2, Nl(l), l.memoizedState = null, t;
  }
  function sh(t, l, e) {
    var a = l.pendingProps, u = (l.flags & 128) !== 0;
    if (l.flags &= -129, t === null) {
      if (ct) {
        if (a.mode === "hidden")
          return t = si(l, a), l.lanes = 536870912, t.memoizedState = { baseLanes: 0, cachePool: null }, wu(null, t);
        if (kc(l), (t = Rt) ? (t = Xm(
          t,
          Yl
        ), t = t !== null && t.data === "&" ? t : null, t !== null && (l.memoizedState = {
          dehydrated: t,
          treeContext: De !== null ? { id: te, overflow: le } : null,
          retryLane: 536870912,
          hydrationErrors: null
        }, e = Wo(t), e.return = l, l.child = e, Wt = l, Rt = null)) : t = null, t === null) throw je(l);
        return l.lanes = 536870912, null;
      }
      return si(l, a);
    }
    var n = t.memoizedState;
    if (n !== null) {
      var i = n.dehydrated;
      if (kc(l), u)
        if (l.flags & 256)
          l.flags &= -257, l = md(
            t,
            l,
            e
          );
        else if (l.memoizedState !== null)
          l.child = t.child, l.flags |= 128, l = null;
        else throw Error(r(558));
      else if (Vt || ra(t, l, e, !1), u = (e & t.childLanes) !== 0, Vt || u) {
        if (Ge.current === null) {
          if (a = At, a !== null && (i = Is(a, e), i !== 0 && i !== n.retryLane))
            throw n.retryLane = i, ca(t, i), Sl(a, t, i), yf;
          Mi();
        }
        l = md(
          t,
          l,
          e
        );
      } else
        t = n.treeContext, Rt = Gl(i.nextSibling), Wt = l, ct = !0, Ue = null, Yl = !1, t !== null && Po(l, t), l = si(l, a), l.flags |= 134221824;
      return l;
    }
    return t = ye(t.child, {
      mode: a.mode,
      children: a.children
    }), t.ref = l.ref, l.child = t, t.return = l, t;
  }
  function $a(t, l) {
    var e = l.ref;
    if (e === null)
      t !== null && t.ref !== null && (l.flags |= 4194816);
    else {
      if (typeof e != "function" && typeof e != "object")
        throw Error(r(284));
      (t === null || t.ref !== e) && (l.flags |= 4194816);
    }
  }
  function gf(t, l, e, a, u) {
    return da(l), e = Fc(
      t,
      l,
      e,
      a,
      void 0,
      u
    ), a = Ic(), t !== null && !Vt ? (Pc(t, l, u), Te(t, l, u)) : (ct && a && Qn(l), l.flags |= 1, kt(t, l, e, u), l.child);
  }
  function vd(t, l, e, a, u, n) {
    return da(l), l.updateQueue = null, e = gr(
      l,
      a,
      e,
      u
    ), yr(t), a = Ic(), t !== null && !Vt ? (Pc(t, l, n), Te(t, l, n)) : (ct && a && Qn(l), l.flags |= 1, kt(t, l, e, n), l.child);
  }
  function hd(t, l, e, a, u) {
    if (da(l), l.stateNode === null) {
      var n = Xa, i = e.contextType;
      typeof i == "object" && i !== null && (n = ll(i)), n = new e(a, n), l.memoizedState = n.state !== null && n.state !== void 0 ? n.state : null, n.updater = vf, l.stateNode = n, n._reactInternals = l, n = l.stateNode, n.props = a, n.state = l.memoizedState, n.refs = {}, Lc(l), i = e.contextType, n.context = typeof i == "object" && i !== null ? ll(i) : Xa, n.state = l.memoizedState, i = e.getDerivedStateFromProps, typeof i == "function" && (mf(
        l,
        e,
        i,
        a
      ), n.state = l.memoizedState), typeof e.getDerivedStateFromProps == "function" || typeof n.getSnapshotBeforeUpdate == "function" || typeof n.UNSAFE_componentWillMount != "function" && typeof n.componentWillMount != "function" || (i = n.state, typeof n.componentWillMount == "function" && n.componentWillMount(), typeof n.UNSAFE_componentWillMount == "function" && n.UNSAFE_componentWillMount(), i !== n.state && vf.enqueueReplaceState(n, n.state, null), Xu(l, a, n, u), Yu(), n.state = l.memoizedState), typeof n.componentDidMount == "function" && (l.flags |= 4194308), a = !0;
    } else if (t === null) {
      n = l.stateNode;
      var c = l.memoizedProps, f = Sa(e, c);
      n.props = f;
      var y = n.context, S = e.contextType;
      i = Xa, typeof S == "object" && S !== null && (i = ll(S));
      var z = e.getDerivedStateFromProps;
      S = typeof z == "function" || typeof n.getSnapshotBeforeUpdate == "function", c = l.pendingProps !== c, S || typeof n.UNSAFE_componentWillReceiveProps != "function" && typeof n.componentWillReceiveProps != "function" || (c || y !== i) && ld(
        l,
        n,
        a,
        i
      ), qe = !1;
      var v = l.memoizedState;
      n.state = v, Xu(l, a, n, u), Yu(), y = l.memoizedState, c || v !== y || qe ? (typeof z == "function" && (mf(
        l,
        e,
        z,
        a
      ), y = l.memoizedState), (f = qe || td(
        l,
        e,
        f,
        a,
        v,
        y,
        i
      )) ? (S || typeof n.UNSAFE_componentWillMount != "function" && typeof n.componentWillMount != "function" || (typeof n.componentWillMount == "function" && n.componentWillMount(), typeof n.UNSAFE_componentWillMount == "function" && n.UNSAFE_componentWillMount()), typeof n.componentDidMount == "function" && (l.flags |= 4194308)) : (typeof n.componentDidMount == "function" && (l.flags |= 4194308), l.memoizedProps = a, l.memoizedState = y), n.props = a, n.state = y, n.context = i, a = f) : (typeof n.componentDidMount == "function" && (l.flags |= 4194308), a = !1);
    } else {
      n = l.stateNode, Zc(t, l), i = l.memoizedProps, S = Sa(e, i), n.props = S, z = l.pendingProps, v = n.context, y = e.contextType, f = Xa, typeof y == "object" && y !== null && (f = ll(y)), c = e.getDerivedStateFromProps, (y = typeof c == "function" || typeof n.getSnapshotBeforeUpdate == "function") || typeof n.UNSAFE_componentWillReceiveProps != "function" && typeof n.componentWillReceiveProps != "function" || (i !== z || v !== f) && ld(
        l,
        n,
        a,
        f
      ), qe = !1, v = l.memoizedState, n.state = v, Xu(l, a, n, u), Yu();
      var b = l.memoizedState;
      i !== z || v !== b || qe || t !== null && t.dependencies !== null && wn(t.dependencies) ? (typeof c == "function" && (mf(
        l,
        e,
        c,
        a
      ), b = l.memoizedState), (S = qe || td(
        l,
        e,
        S,
        a,
        v,
        b,
        f
      ) || t !== null && t.dependencies !== null && wn(t.dependencies)) ? (y || typeof n.UNSAFE_componentWillUpdate != "function" && typeof n.componentWillUpdate != "function" || (typeof n.componentWillUpdate == "function" && n.componentWillUpdate(a, b, f), typeof n.UNSAFE_componentWillUpdate == "function" && n.UNSAFE_componentWillUpdate(
        a,
        b,
        f
      )), typeof n.componentDidUpdate == "function" && (l.flags |= 4), typeof n.getSnapshotBeforeUpdate == "function" && (l.flags |= 1024)) : (typeof n.componentDidUpdate != "function" || i === t.memoizedProps && v === t.memoizedState || (l.flags |= 4), typeof n.getSnapshotBeforeUpdate != "function" || i === t.memoizedProps && v === t.memoizedState || (l.flags |= 1024), l.memoizedProps = a, l.memoizedState = b), n.props = a, n.state = b, n.context = f, a = S) : (typeof n.componentDidUpdate != "function" || i === t.memoizedProps && v === t.memoizedState || (l.flags |= 4), typeof n.getSnapshotBeforeUpdate != "function" || i === t.memoizedProps && v === t.memoizedState || (l.flags |= 1024), a = !1);
    }
    return n = a, $a(t, l), a = (l.flags & 128) !== 0, n || a ? (n = l.stateNode, e = a && typeof e.getDerivedStateFromError != "function" ? null : n.render(), l.flags |= 1, t !== null && a ? (l.child = ga(
      l,
      t.child,
      null,
      u
    ), l.child = ga(
      l,
      null,
      e,
      u
    )) : kt(t, l, e, u), l.memoizedState = n.state, t = l.child) : t = Te(
      t,
      l,
      u
    ), t;
  }
  function yd(t, l, e, a) {
    return sa(), l.flags |= 256, kt(t, l, e, a), l.child;
  }
  var bf = {
    dehydrated: null,
    treeContext: null,
    retryLane: 0,
    hydrationErrors: null
  };
  function Sf(t) {
    return { baseLanes: t, cachePool: nr() };
  }
  function pf(t, l, e) {
    return t = t !== null ? t.childLanes & ~e : 0, l && (t |= Al), t;
  }
  function gd(t, l, e) {
    var a = l.pendingProps, u = !1, n = (l.flags & 128) !== 0, i;
    if ((i = n) || (i = t !== null && t.memoizedState === null ? !1 : (al.current & 2) !== 0), i && (u = !0, l.flags &= -129), i = (l.flags & 32) !== 0, l.flags &= -33, t === null) {
      if (ct) {
        if (u ? Qe(l) : Le(), (t = Rt) ? (t = Xm(
          t,
          Yl
        ), t = t !== null && t.data !== "&" ? t : null, t !== null && (l.memoizedState = {
          dehydrated: t,
          treeContext: De !== null ? { id: te, overflow: le } : null,
          retryLane: 536870912,
          hydrationErrors: null
        }, e = Wo(t), e.return = l, l.child = e, Wt = l, Rt = null)) : t = null, t === null) throw je(l);
        return Ss(t) ? l.lanes = 32 : l.lanes = 536870912, null;
      }
      return n = a.children, a = a.fallback, u ? (Le(), u = l.mode, n = oi(
        { mode: "hidden", children: n },
        u
      ), a = fa(
        a,
        u,
        e,
        null
      ), n.return = l, a.return = l, n.sibling = a, l.child = n, a = l.child, a.memoizedState = Sf(e), a.childLanes = pf(
        t,
        i,
        e
      ), l.memoizedState = bf, wu(null, a)) : (Qe(l), _f(l, n));
    }
    var c = t.memoizedState;
    if (c !== null) {
      var f = c.dehydrated;
      if (f !== null)
        return oh(
          t,
          l,
          n,
          i,
          a,
          f,
          c,
          e
        );
    }
    return u ? (Le(), u = a.fallback, n = l.mode, c = t.child, f = c.sibling, a = ye(c, {
      mode: "hidden",
      children: a.children
    }), a.subtreeFlags = c.subtreeFlags & 1206910976, f !== null ? u = ye(f, u) : (u = fa(
      u,
      n,
      e,
      null
    ), u.flags |= 2), u.return = l, a.return = l, a.sibling = u, l.child = a, wu(null, a), a = l.child, u = t.child.memoizedState, u === null ? u = Sf(e) : (n = u.cachePool, n !== null ? (c = Zt._currentValue, n = n.parent !== c ? { parent: c, pool: c } : n) : n = nr(), u = {
      baseLanes: u.baseLanes | e,
      cachePool: n
    }), a.memoizedState = u, a.childLanes = pf(
      t,
      i,
      e
    ), l.memoizedState = bf, wu(t.child, a)) : (Qe(l), e = t.child, t = e.sibling, e = ye(e, {
      mode: "visible",
      children: a.children
    }), e.return = l, e.sibling = null, t !== null && (i = l.deletions, i === null ? (l.deletions = [t], l.flags |= 16) : i.push(t)), l.child = e, l.memoizedState = null, e);
  }
  function _f(t, l) {
    return l = oi(
      { mode: "visible", children: l },
      t.mode
    ), l.return = t, t.child = l;
  }
  function oi(t, l) {
    return t = hl(22, t, null, l), t.lanes = 0, t;
  }
  function ri(t, l, e) {
    return ga(l, t.child, null, e), t = _f(
      l,
      l.pendingProps.children
    ), t.flags |= 2, l.memoizedState = null, t;
  }
  function oh(t, l, e, a, u, n, i, c) {
    if (e)
      return l.flags & 256 ? (Qe(l), l.flags &= -257, ri(
        t,
        l,
        c
      )) : l.memoizedState !== null ? (Le(), l.child = t.child, l.flags |= 128, null) : (Le(), n = u.fallback, i = l.mode, u = oi(
        { mode: "visible", children: u.children },
        i
      ), n = fa(
        n,
        i,
        c,
        null
      ), n.flags |= 2, u.return = l, n.return = l, u.sibling = n, l.child = u, ga(l, t.child, null, c), u = l.child, u.memoizedState = Sf(c), u.childLanes = pf(
        t,
        a,
        c
      ), l.memoizedState = bf, wu(null, u));
    if (Qe(l), Ss(n)) {
      if (a = n.nextSibling && n.nextSibling.dataset, a) var f = a.dgst;
      return a = f, a !== "" && (u = Error(r(419)), u.stack = "", u.digest = a, Du({ value: u, source: null, stack: null })), ri(
        t,
        l,
        c
      );
    }
    if (Vt || ra(t, l, c, !1), a = (c & t.childLanes) !== 0, Vt || a) {
      if (Ge.current !== null)
        return ri(
          t,
          l,
          c
        );
      if (a = At, a !== null && (u = Is(
        a,
        c
      ), u !== 0 && u !== i.retryLane))
        throw i.retryLane = u, ca(t, u), Sl(a, t, u), yf;
      return bs(n) || Mi(), ri(
        t,
        l,
        c
      );
    }
    return bs(n) ? (l.flags |= 192, l.child = t.child, null) : (t = i.treeContext, Rt = Gl(n.nextSibling), Wt = l, ct = !0, Ue = null, Yl = !1, t !== null && Po(l, t), l = _f(
      l,
      u.children
    ), l.flags |= 134221824, l);
  }
  function bd(t, l, e) {
    t.lanes |= l;
    var a = t.alternate;
    a !== null && (a.lanes |= l), Zn(t.return, l, e);
  }
  function Sd(t) {
    for (var l = null; t !== null; ) {
      var e = t.alternate;
      e !== null && In(e) === null && (l = t), t = t.sibling;
    }
    return l;
  }
  function di(t, l, e, a, u, n) {
    var i = t.memoizedState;
    i === null ? t.memoizedState = {
      isBackwards: l,
      rendering: null,
      renderingStartTime: 0,
      last: a,
      tail: e,
      tailMode: u,
      treeForkCount: n
    } : (i.isBackwards = l, i.rendering = null, i.renderingStartTime = 0, i.last = a, i.tail = e, i.tailMode = u, i.treeForkCount = n);
  }
  function Tf(t) {
    var l = t.child;
    for (t.child = null; l !== null; ) {
      var e = l.sibling;
      l.sibling = t.child, t.child = l, l = e;
    }
  }
  function xf(t, l, e) {
    var a = l.pendingProps, u = a.revealOrder, n = a.tail;
    a = a.children;
    var i = al.current;
    if (l.flags & 128)
      return Gu(l, i), null;
    var c = (i & 2) !== 0;
    if (c ? (i = i & 1 | 2, l.flags |= 128) : i &= 1, Gu(l, i), u === "backwards" && t !== null ? (Tf(t), kt(t, l, a, e), Tf(t)) : kt(t, l, a, e), a = ct ? Ru : 0, !c && t !== null && (t.flags & 128) !== 0)
      t: for (t = l.child; t !== null; ) {
        if (t.tag === 13)
          t.memoizedState !== null && bd(t, e, l);
        else if (t.tag === 19)
          bd(t, e, l);
        else if (t.child !== null) {
          t.child.return = t, t = t.child;
          continue;
        }
        if (t === l) break t;
        for (; t.sibling === null; ) {
          if (t.return === null || t.return === l)
            break t;
          t = t.return;
        }
        t.sibling.return = t.return, t = t.sibling;
      }
    switch (u) {
      case "backwards":
        e = Sd(l.child), e === null ? (u = l.child, l.child = null) : (u = e.sibling, e.sibling = null, Tf(l)), di(
          l,
          !0,
          u,
          null,
          n,
          a
        );
        break;
      case "unstable_legacy-backwards":
        for (e = null, u = l.child, l.child = null; u !== null; ) {
          if (t = u.alternate, t !== null && In(t) === null) {
            l.child = u;
            break;
          }
          t = u.sibling, u.sibling = e, e = u, u = t;
        }
        di(
          l,
          !0,
          e,
          null,
          n,
          a
        );
        break;
      case "together":
        di(
          l,
          !1,
          null,
          null,
          void 0,
          a
        );
        break;
      case "independent":
        l.memoizedState = null;
        break;
      default:
        e = Sd(l.child), e === null ? (u = l.child, l.child = null) : (u = e.sibling, e.sibling = null), di(
          l,
          !1,
          u,
          e,
          n,
          a
        );
    }
    return l.child;
  }
  function pd(t, l, e) {
    var a = l.pendingProps;
    return He(l, l.type, a.value), kt(t, l, a.children, e), l.child;
  }
  function Te(t, l, e) {
    if (t !== null && (l.dependencies = t.dependencies), Ke |= l.lanes, (e & l.childLanes) === 0)
      if (t !== null) {
        if (ra(
          t,
          l,
          e,
          !1
        ), (e & l.childLanes) === 0)
          return null;
      } else return null;
    if (t !== null && l.child !== t.child)
      throw Error(r(153));
    if (l.child !== null) {
      for (t = l.child, e = ye(t, t.pendingProps), l.child = e, e.return = l; t.sibling !== null; )
        t = t.sibling, e = e.sibling = ye(t, t.pendingProps), e.return = l;
      e.sibling = null;
    }
    return l.child;
  }
  function Ef(t, l) {
    return (t.lanes & l) !== 0 ? !0 : (t = t.dependencies, !!(t !== null && wn(t)));
  }
  function rh(t, l, e) {
    switch (l.tag) {
      case 3:
        gn(l, l.stateNode.containerInfo), He(l, Zt, t.memoizedState.cache), sa();
        break;
      case 27:
      case 5:
        Wi(l);
        break;
      case 4:
        gn(l, l.stateNode.containerInfo);
        break;
      case 10:
        He(
          l,
          l.type,
          l.memoizedProps.value
        );
        break;
      case 31:
        if (l.memoizedState !== null)
          return l.flags |= 128, kc(l), null;
        break;
      case 13:
        var a = l.memoizedState;
        if (a !== null) {
          if (a.dehydrated !== null)
            return Qe(l), l.flags |= 128, null;
          a = ra(
            t,
            l,
            e,
            !1
          );
          var u = l.child.childLanes;
          return a || (e & u) !== 0 ? gd(t, l, e) : (Qe(l), t = Te(
            t,
            l,
            e
          ), t !== null ? t.sibling : null);
        }
        Qe(l);
        break;
      case 19:
        if (l.flags & 128)
          return xf(
            t,
            l,
            e
          );
        if (u = (t.flags & 128) !== 0, a = (e & l.childLanes) !== 0, a || (ra(
          t,
          l,
          e,
          !1
        ), a = (e & l.childLanes) !== 0), u) {
          if (a)
            return xf(
              t,
              l,
              e
            );
          l.flags |= 128;
        }
        if (u = l.memoizedState, u !== null && (u.rendering = null, u.tail = null, u.lastEffect = null), Gu(l, al.current), a) break;
        return null;
      case 22:
        return l.lanes = 0, rd(
          t,
          l,
          e,
          l.pendingProps
        );
      case 24:
        He(l, Zt, t.memoizedState.cache);
    }
    return Te(t, l, e);
  }
  function _d(t, l, e) {
    if (t !== null)
      if (t.memoizedProps !== l.pendingProps)
        Vt = !0;
      else {
        if (!Ef(t, e) && (l.flags & 128) === 0)
          return Vt = !1, rh(
            t,
            l,
            e
          );
        Vt = (t.flags & 131072) !== 0;
      }
    else
      Vt = !1, ct && (l.flags & 1048576) !== 0 && Io(l, Ru, l.index);
    switch (l.lanes = 0, l.tag) {
      case 16:
        t: {
          var a = l.pendingProps;
          if (t = ha(l.elementType), l.type = t, typeof t == "function")
            Cc(t) ? (a = Sa(t, a), l.tag = 1, l = hd(
              null,
              l,
              t,
              a,
              e
            )) : (l.tag = 0, l = gf(
              null,
              l,
              t,
              a,
              e
            ));
          else {
            if (t != null) {
              var u = t.$$typeof;
              if (u === B) {
                l.tag = 11, l = fd(
                  null,
                  l,
                  t,
                  a,
                  e
                );
                break t;
              } else if (u === Tt) {
                l.tag = 14, l = sd(
                  null,
                  l,
                  t,
                  a,
                  e
                );
                break t;
              } else if (u === Yt) {
                l.tag = 10, l.type = t, l = pd(
                  null,
                  l,
                  e
                );
                break t;
              }
            }
            throw l = w(t) || t, Error(r(306, l, ""));
          }
        }
        return l;
      case 0:
        return gf(
          t,
          l,
          l.type,
          l.pendingProps,
          e
        );
      case 1:
        return a = l.type, u = Sa(
          a,
          l.pendingProps
        ), hd(
          t,
          l,
          a,
          u,
          e
        );
      case 3:
        t: {
          if (gn(
            l,
            l.stateNode.containerInfo
          ), t === null) throw Error(r(387));
          a = l.pendingProps;
          var n = l.memoizedState;
          u = n.element, Zc(t, l), Xu(l, a, null, e);
          var i = l.memoizedState;
          if (a = i.cache, He(l, Zt, a), a !== n.cache && qc(
            l,
            [Zt],
            e,
            !0
          ), Yu(), a = i.element, n.isDehydrated)
            if (n = {
              element: a,
              isDehydrated: !1,
              cache: i.cache
            }, l.updateQueue.baseState = n, l.memoizedState = n, l.flags & 256) {
              l = yd(
                t,
                l,
                a,
                e
              );
              break t;
            } else if (a !== u) {
              u = Hl(
                Error(r(424)),
                l
              ), Du(u), l = yd(
                t,
                l,
                a,
                e
              );
              break t;
            } else
              for (t = l.stateNode.containerInfo, t.nodeType === 9 ? t = t.body : t = t.nodeName === "HTML" ? t.ownerDocument.body : t, Rt = Gl(t.firstChild), Wt = l, ct = !0, Ue = null, Yl = !0, e = rr(
                l,
                null,
                a,
                e
              ), l.child = e; e; )
                e.flags = e.flags & -3 | 134221824, e = e.sibling;
          else {
            if (sa(), a === u) {
              l = Te(
                t,
                l,
                e
              );
              break t;
            }
            kt(t, l, a, e);
          }
          l = l.child;
        }
        return l;
      case 26:
        return $a(t, l), t === null ? (e = Km(
          l.type,
          null,
          l.pendingProps,
          null
        )) ? l.memoizedState = e : ct || (l.stateNode = Nm(
          l.type,
          l.pendingProps,
          Oe.current,
          l
        )) : l.memoizedState = Km(
          l.type,
          t.memoizedProps,
          l.pendingProps,
          t.memoizedState
        ), null;
      case 27:
        return Wi(l), t === null && ct && (a = l.stateNode = Lm(
          l.type,
          l.pendingProps,
          Oe.current
        ), Wt = l, Yl = !0, u = Rt, We(l.type) ? (ps = u, Rt = Gl(a.firstChild)) : Rt = u), kt(
          t,
          l,
          l.pendingProps.children,
          e
        ), $a(t, l), t === null && (l.flags |= 4194304), l.child;
      case 5:
        return t === null && ct && ((u = a = Rt) && (a = ny(
          a,
          l.type,
          l.pendingProps,
          Yl
        ), a !== null ? (l.stateNode = a, Wt = l, Rt = Gl(a.firstChild), Yl = !1, u = !0) : u = !1), u || je(l)), Wi(l), u = l.type, n = l.pendingProps, i = t !== null ? t.memoizedProps : null, a = n.children, rs(u, n) ? a = null : i !== null && rs(u, i) && (l.flags |= 32), l.memoizedState !== null && (u = Fc(
          t,
          l,
          th,
          null,
          null,
          e
        ), mu._currentValue = u), $a(t, l), kt(t, l, a, e), l.child;
      case 6:
        return t === null && ct && ((t = e = Rt) && (e = iy(
          e,
          l.pendingProps,
          Yl
        ), e !== null ? (l.stateNode = e, Wt = l, Rt = null, t = !0) : t = !1), t || je(l)), null;
      case 13:
        return gd(t, l, e);
      case 4:
        return gn(
          l,
          l.stateNode.containerInfo
        ), a = l.pendingProps, t === null ? l.child = ga(
          l,
          null,
          a,
          e
        ) : kt(t, l, a, e), l.child;
      case 11:
        return fd(
          t,
          l,
          l.type,
          l.pendingProps,
          e
        );
      case 7:
        return a = l.pendingProps, $a(t, l), kt(t, l, a, e), l.child;
      case 8:
        return kt(
          t,
          l,
          l.pendingProps.children,
          e
        ), l.child;
      case 12:
        return kt(
          t,
          l,
          l.pendingProps.children,
          e
        ), l.child;
      case 10:
        return pd(t, l, e);
      case 9:
        return u = l.type._context, a = l.pendingProps.children, da(l), u = ll(u), a = a(u), l.flags |= 1, kt(t, l, a, e), l.child;
      case 14:
        return sd(
          t,
          l,
          l.type,
          l.pendingProps,
          e
        );
      case 15:
        return od(
          t,
          l,
          l.type,
          l.pendingProps,
          e
        );
      case 19:
        return xf(t, l, e);
      case 31:
        return sh(t, l, e);
      case 22:
        return rd(
          t,
          l,
          e,
          l.pendingProps
        );
      case 24:
        return da(l), a = ll(Zt), t === null ? (u = Gc(), u === null && (u = At, n = Yc(), u.pooledCache = n, n.refCount++, n !== null && (u.pooledCacheLanes |= e), u = n), l.memoizedState = { parent: a, cache: u }, Lc(l), He(l, Zt, u)) : ((t.lanes & e) !== 0 && (Zc(t, l), Xu(l, null, null, e), Yu()), u = t.memoizedState, n = l.memoizedState, u.parent !== a ? (u = { parent: a, cache: a }, l.memoizedState = u, l.lanes === 0 && (l.memoizedState = l.updateQueue.baseState = u), He(l, Zt, a)) : (a = n.cache, He(l, Zt, a), a !== u.cache && qc(
          l,
          [Zt],
          e,
          !0
        ))), kt(
          t,
          l,
          l.pendingProps.children,
          e
        ), l.child;
      case 30:
        return l.stateNode === null && (l.stateNode = {
          autoName: null,
          paired: null,
          clones: null,
          ref: null
        }), a = l.pendingProps, a.name != null && a.name !== "auto" ? l.flags |= t === null ? 18882560 : 18874368 : ct && Qn(l), t !== null && t.memoizedProps.name !== a.name ? l.flags |= 4194816 : $a(t, l), kt(t, l, a.children, e), l.child;
      case 29:
        throw l.pendingProps;
    }
    throw Error(r(156, l.tag));
  }
  function xe(t) {
    t.flags |= 4;
  }
  function Nf(t, l, e, a, u) {
    var n;
    if ((n = (t.mode & 32) !== 0) && (n = e === null ? Wm(l, a) : Wm(l, a) && (a.src !== e.src || a.srcSet !== e.srcSet)), n) {
      if (t.flags |= 16777216, (u & 335544128) === u)
        if (t.stateNode.complete) t.flags |= 8192;
        else if (em()) t.flags |= 8192;
        else
          throw ya = kn, Qc;
    } else t.flags &= -16777217;
  }
  function Td(t, l) {
    if (l.type !== "stylesheet" || (l.state.loading & 4) !== 0)
      t.flags &= -16777217;
    else if (t.flags |= 16777216, !Fm(l))
      if (em()) t.flags |= 8192;
      else
        throw ya = kn, Qc;
  }
  function mi(t, l) {
    l !== null && (t.flags |= 4), t.flags & 16384 && (l = t.tag !== 22 ? $s() : 536870912, t.lanes |= l, tu |= l);
  }
  function Vu(t, l) {
    if (!ct)
      switch (t.tailMode) {
        case "visible":
          break;
        case "collapsed":
          for (var e = t.tail, a = null; e !== null; )
            e.alternate !== null && (a = e), e = e.sibling;
          a === null ? l || t.tail === null ? t.tail = null : t.tail.sibling = null : a.sibling = null;
          break;
        default:
          for (l = t.tail, e = null; l !== null; )
            l.alternate !== null && (e = l), l = l.sibling;
          e === null ? t.tail = null : e.sibling = null;
      }
  }
  function Dt(t) {
    var l = t.alternate !== null && t.alternate.child === t.child, e = 0, a = 0;
    if (l)
      for (var u = t.child; u !== null; )
        e |= u.lanes | u.childLanes, a |= u.subtreeFlags & 1206910976, a |= u.flags & 1206910976, u.return = t, u = u.sibling;
    else
      for (u = t.child; u !== null; )
        e |= u.lanes | u.childLanes, a |= u.subtreeFlags, a |= u.flags, u.return = t, u = u.sibling;
    return t.subtreeFlags |= a, t.childLanes = e, l;
  }
  function dh(t, l, e) {
    var a = l.pendingProps;
    switch (Uc(l), l.tag) {
      case 16:
      case 15:
      case 0:
      case 11:
      case 7:
      case 8:
      case 12:
      case 9:
      case 14:
        return Dt(l), null;
      case 1:
        return Dt(l), null;
      case 3:
        return e = l.stateNode, a = null, t !== null && (a = t.memoizedState.cache), l.memoizedState.cache !== a && (l.flags |= 2048), Se(Zt), za(), e.pendingContext && (e.context = e.pendingContext, e.pendingContext = null), (t === null || t.child === null) && (La(l) ? xe(l) : t === null || t.memoizedState.isDehydrated && (l.flags & 256) === 0 || (l.flags |= 1024, Hc())), Dt(l), null;
      case 26:
        var u = l.type, n = l.memoizedState;
        return t === null ? (xe(l), n !== null ? (Dt(l), Td(l, n)) : (Dt(l), Nf(
          l,
          u,
          null,
          a,
          e
        ))) : n ? n !== t.memoizedState ? (xe(l), Dt(l), Td(l, n)) : (Dt(l), l.flags &= -16777217) : (t = t.memoizedProps, t !== a && xe(l), Dt(l), Nf(
          l,
          u,
          t,
          a,
          e
        )), null;
      case 27:
        if (bn(l), e = Oe.current, u = l.type, t !== null && l.stateNode != null)
          t.memoizedProps !== a && xe(l);
        else {
          if (!a) {
            if (l.stateNode === null)
              throw Error(r(166));
            return Dt(l), l.subtreeFlags &= -33554433, null;
          }
          t = Il.current, La(l) ? tr(l) : (t = Lm(u, a, e), l.stateNode = t, xe(l));
        }
        return Dt(l), l.subtreeFlags &= -33554433, null;
      case 5:
        if (bn(l), u = l.type, t !== null && l.stateNode != null)
          t.memoizedProps !== a && xe(l);
        else {
          if (!a) {
            if (l.stateNode === null)
              throw Error(r(166));
            return Dt(l), l.subtreeFlags &= -33554433, null;
          }
          if (n = Il.current, La(l))
            tr(l);
          else {
            var i = en(
              Oe.current
            );
            switch (n) {
              case 1:
                n = i.createElementNS(
                  "http://www.w3.org/2000/svg",
                  u
                );
                break;
              case 2:
                n = i.createElementNS(
                  "http://www.w3.org/1998/Math/MathML",
                  u
                );
                break;
              default:
                switch (u) {
                  case "svg":
                    n = i.createElementNS(
                      "http://www.w3.org/2000/svg",
                      u
                    );
                    break;
                  case "math":
                    n = i.createElementNS(
                      "http://www.w3.org/1998/Math/MathML",
                      u
                    );
                    break;
                  case "script":
                    n = i.createElement("div"), n.innerHTML = "<script><\/script>", n = n.removeChild(
                      n.firstChild
                    );
                    break;
                  case "select":
                    n = typeof a.is == "string" ? i.createElement("select", {
                      is: a.is
                    }) : i.createElement("select"), a.multiple ? n.multiple = !0 : a.size && (n.size = a.size);
                    break;
                  default:
                    n = typeof a.is == "string" ? i.createElement(u, { is: a.is }) : i.createElement(u);
                }
            }
            n[tl] = l, n[vl] = a;
            t: for (i = l.child; i !== null; ) {
              if (i.tag === 5 || i.tag === 6)
                n.appendChild(i.stateNode);
              else if (i.tag !== 4 && i.tag !== 27 && i.child !== null) {
                i.child.return = i, i = i.child;
                continue;
              }
              if (i === l) break t;
              for (; i.sibling === null; ) {
                if (i.return === null || i.return === l)
                  break t;
                i = i.return;
              }
              i.sibling.return = i.return, i = i.sibling;
            }
            l.stateNode = n;
            t: switch (nl(n, u, a), u) {
              case "button":
              case "input":
              case "select":
              case "textarea":
                a = !!a.autoFocus;
                break t;
              case "img":
                a = !0;
                break t;
              default:
                a = !1;
            }
            a && xe(l);
          }
        }
        return Dt(l), l.subtreeFlags &= -33554433, Nf(
          l,
          l.type,
          t === null ? null : t.memoizedProps,
          l.pendingProps,
          e
        ), null;
      case 6:
        if (t && l.stateNode != null)
          t.memoizedProps !== a && xe(l);
        else {
          if (typeof a != "string" && l.stateNode === null)
            throw Error(r(166));
          if (t = Oe.current, La(l)) {
            if (t = l.stateNode, e = l.memoizedProps, a = null, u = Wt, u !== null)
              switch (u.tag) {
                case 27:
                case 5:
                  a = u.memoizedProps;
              }
            t[tl] = l, t = !!(t.nodeValue === e || a !== null && a.suppressHydrationWarning === !0 || _m(t.nodeValue, e)), t || je(l, !0);
          } else
            t = en(t).createTextNode(
              a
            ), t[tl] = l, l.stateNode = t;
        }
        return Dt(l), null;
      case 31:
        if (e = l.memoizedState, t === null || t.memoizedState !== null) {
          if (a = La(l), e !== null) {
            if (t === null) {
              if (!a) throw Error(r(318));
              if (t = l.memoizedState, t = t !== null ? t.dehydrated : null, !t) throw Error(r(557));
              t[tl] = l;
            } else
              sa(), (l.flags & 128) === 0 && (l.memoizedState = null), l.flags |= 4;
            Dt(l), t = !1;
          } else
            e = Hc(), t !== null && t.memoizedState !== null && (t.memoizedState.hydrationErrors = e), t = !0;
          if (!t)
            return l.flags & 256 ? (Nl(l), l) : (Nl(l), null);
          if ((l.flags & 128) !== 0)
            throw Error(r(558));
        }
        return Dt(l), null;
      case 13:
        if (a = l.memoizedState, t === null || t.memoizedState !== null && t.memoizedState.dehydrated !== null) {
          if (u = La(l), a !== null && a.dehydrated !== null) {
            if (t === null) {
              if (!u) throw Error(r(318));
              if (u = l.memoizedState, u = u !== null ? u.dehydrated : null, !u) throw Error(r(317));
              u[tl] = l;
            } else
              sa(), (l.flags & 128) === 0 && (l.memoizedState = null), l.flags |= 4;
            Dt(l), u = !1;
          } else
            u = Hc(), t !== null && t.memoizedState !== null && (t.memoizedState.hydrationErrors = u), u = !0;
          if (!u)
            return l.flags & 256 ? (Nl(l), l) : (Nl(l), null);
        }
        return Nl(l), (l.flags & 128) !== 0 ? (l.lanes = e, l) : (e = a !== null, t = t !== null && t.memoizedState !== null, e && (a = l.child, u = null, a.alternate !== null && a.alternate.memoizedState !== null && a.alternate.memoizedState.cachePool !== null && (u = a.alternate.memoizedState.cachePool.pool), n = null, a.memoizedState !== null && a.memoizedState.cachePool !== null && (n = a.memoizedState.cachePool.pool), n !== u && (a.flags |= 2048)), e !== t && e && (l.child.flags |= 8192), mi(l, l.updateQueue), Dt(l), null);
      case 4:
        return za(), t === null && is(l.stateNode.containerInfo), l.flags |= 67108864, Dt(l), null;
      case 10:
        return Se(l.type), Dt(l), null;
      case 19:
        if ($c(l), a = l.memoizedState, a === null) return Dt(l), null;
        if (u = (l.flags & 128) !== 0, n = a.rendering, n === null)
          if (u) Vu(a, !1);
          else {
            if (Gt !== 0 || t !== null && (t.flags & 128) !== 0)
              for (t = l.child; t !== null; ) {
                if (n = In(t), n !== null) {
                  for (l.flags |= 128, Vu(a, !1), t = n.updateQueue, l.updateQueue = t, mi(l, t), l.subtreeFlags = 0, t = e, e = l.child; e !== null; )
                    $o(e, t), e = e.sibling;
                  return Gu(
                    l,
                    al.current & 1 | 2
                  ), ct && ge(l, a.treeForkCount), l.child;
                }
                t = t.sibling;
              }
            a.tail !== null && pl() > Ni && (l.flags |= 128, u = !0, Vu(a, !1), l.lanes = 4194304);
          }
        else {
          if (!u)
            if (t = In(n), t !== null) {
              if (l.flags |= 128, u = !0, t = t.updateQueue, l.updateQueue = t, mi(l, t), Vu(a, !0), a.tail === null && a.tailMode !== "collapsed" && a.tailMode !== "visible" && !n.alternate && !ct)
                return Dt(l), null;
            } else
              2 * pl() - a.renderingStartTime > Ni && e !== 536870912 && (l.flags |= 128, u = !0, Vu(a, !1), l.lanes = 4194304);
          a.isBackwards ? (n.sibling = l.child, l.child = n) : (t = a.last, t !== null ? t.sibling = n : l.child = n, a.last = n);
        }
        if (a.tail !== null) {
          t = a.tail;
          t: {
            for (e = t; e !== null; ) {
              if (e.alternate !== null) {
                e = !1;
                break t;
              }
              e = e.sibling;
            }
            e = !0;
          }
          return a.rendering = t, a.tail = t.sibling, a.renderingStartTime = pl(), t.sibling = null, n = al.current, n = u ? n & 1 | 2 : n & 1, a.tailMode === "visible" || a.tailMode === "collapsed" || !e || ct ? Gu(l, n) : (e = n, Ct(el, l), Ct(al, e), fl === null && (fl = l)), ct && ge(l, a.treeForkCount), t;
        }
        return Dt(l), null;
      case 22:
      case 23:
        return Nl(l), Jc(), a = l.memoizedState !== null, t !== null ? t.memoizedState !== null !== a && (l.flags |= 8192) : a && (l.flags |= 8192), a ? (e & 536870912) !== 0 && (l.flags & 128) === 0 && (Dt(l), l.subtreeFlags & 6 && (l.flags |= 8192)) : Dt(l), e = l.updateQueue, e !== null && mi(l, e.retryQueue), e = null, t !== null && t.memoizedState !== null && t.memoizedState.cachePool !== null && (e = t.memoizedState.cachePool.pool), a = null, l.memoizedState !== null && l.memoizedState.cachePool !== null && (a = l.memoizedState.cachePool.pool), a !== e && (l.flags |= 2048), t !== null && Qt(va), null;
      case 24:
        return e = null, t !== null && (e = t.memoizedState.cache), l.memoizedState.cache !== e && (l.flags |= 2048), Se(Zt), Dt(l), null;
      case 25:
        return null;
      case 30:
        return l.flags |= 33554432, Dt(l), null;
    }
    throw Error(r(156, l.tag));
  }
  function mh(t, l) {
    switch (Uc(l), l.tag) {
      case 1:
        return t = l.flags, t & 65536 ? (l.flags = t & -65537 | 128, l) : null;
      case 3:
        return Se(Zt), za(), t = l.flags, (t & 65536) !== 0 && (t & 128) === 0 ? (l.flags = t & -65537 | 128, l) : null;
      case 26:
      case 27:
      case 5:
        return bn(l), null;
      case 31:
        if (l.memoizedState !== null) {
          if (Nl(l), l.alternate === null)
            throw Error(r(340));
          sa();
        }
        return t = l.flags, t & 65536 ? (l.flags = t & -65537 | 128, l) : null;
      case 13:
        if (Nl(l), t = l.memoizedState, t !== null && t.dehydrated !== null) {
          if (l.alternate === null)
            throw Error(r(340));
          sa();
        }
        return t = l.flags, t & 65536 ? (l.flags = t & -65537 | 128, l) : null;
      case 19:
        return $c(l), t = l.flags, t & 65536 ? (l.flags = t & -65537 | 128, t = l.memoizedState, t !== null && (t.rendering = null, t.tail = null), l.flags |= 4, l) : null;
      case 4:
        return za(), null;
      case 10:
        return Se(l.type), null;
      case 22:
      case 23:
        return Nl(l), Jc(), t !== null && Qt(va), t = l.flags, t & 65536 ? (l.flags = t & -65537 | 128, l) : null;
      case 24:
        return Se(Zt), null;
      case 25:
        return null;
      default:
        return null;
    }
  }
  function xd(t, l) {
    switch (Uc(l), l.tag) {
      case 3:
        Se(Zt), za();
        break;
      case 26:
      case 27:
      case 5:
        bn(l);
        break;
      case 4:
        za();
        break;
      case 31:
        l.memoizedState !== null && Nl(l);
        break;
      case 13:
        Nl(l);
        break;
      case 19:
        $c(l);
        break;
      case 10:
        Se(l.type);
        break;
      case 22:
      case 23:
        Nl(l), Jc(), t !== null && Qt(va);
        break;
      case 24:
        Se(Zt);
    }
  }
  function Ku(t, l) {
    try {
      var e = l.updateQueue, a = e !== null ? e.lastEffect : null;
      if (a !== null) {
        var u = a.next;
        e = u;
        do {
          if ((e.tag & t) === t) {
            a = void 0;
            var n = e.create, i = e.inst;
            a = n(), i.destroy = a;
          }
          e = e.next;
        } while (e !== u);
      }
    } catch (c) {
      Et(l, l.return, c);
    }
  }
  function Ze(t, l, e) {
    try {
      var a = l.updateQueue, u = a !== null ? a.lastEffect : null;
      if (u !== null) {
        var n = u.next;
        a = n;
        do {
          if ((a.tag & t) === t) {
            var i = a.inst, c = i.destroy;
            if (c !== void 0) {
              i.destroy = void 0, u = l;
              var f = e, y = c;
              try {
                y();
              } catch (S) {
                Et(
                  u,
                  f,
                  S
                );
              }
            }
          }
          a = a.next;
        } while (a !== n);
      }
    } catch (S) {
      Et(l, l.return, S);
    }
  }
  function Ed(t) {
    var l = t.updateQueue;
    if (l !== null) {
      var e = t.stateNode;
      try {
        mr(l, e);
      } catch (a) {
        Et(t, t.return, a);
      }
    }
  }
  function Nd(t, l, e) {
    e.props = Sa(
      t.type,
      t.memoizedProps
    ), e.state = t.memoizedState;
    try {
      e.componentWillUnmount();
    } catch (a) {
      Et(t, l, a);
    }
  }
  function ee(t, l) {
    try {
      var e = t.ref;
      if (e !== null) {
        switch (t.tag) {
          case 26:
          case 27:
          case 5:
            var a = t.stateNode;
            break;
          case 30:
            var u = t.stateNode, n = ve(t.memoizedProps, u);
            (u.ref === null || u.ref.name !== n) && (u.ref = Dm(n)), a = u.ref;
            break;
          case 7:
            if (t.stateNode === null) {
              var i = new Cl(t);
              p(
                t.child,
                !1,
                ay,
                i,
                void 0,
                void 0
              ), t.stateNode = i;
            }
            a = t.stateNode;
            break;
          default:
            a = t.stateNode;
        }
        typeof e == "function" ? t.refCleanup = e(a) : e.current = a;
      }
    } catch (c) {
      Et(t, l, c);
    }
  }
  function ul(t, l) {
    var e = t.ref, a = t.refCleanup;
    if (e !== null)
      if (typeof a == "function")
        try {
          a();
        } catch (u) {
          Et(t, l, u);
        } finally {
          t.refCleanup = null, t = t.alternate, t != null && (t.refCleanup = null);
        }
      else if (typeof e == "function")
        try {
          e(null);
        } catch (u) {
          Et(t, l, u);
        }
      else e.current = null;
  }
  function vi(t, l) {
    if ((t.tag === 5 || t.tag === 27 || t.tag === 6) && t.alternate === null && l !== null)
      for (var e = 0; e < l.length; e++)
        Ym(
          t.stateNode,
          l[e]
        );
  }
  function zd(t) {
    for (var l = t.return; l !== null && (Of(l) && Ym(t.stateNode, l.stateNode), !zf(l)); )
      l = l.return;
  }
  function Ju(t) {
    for (var l = t.return; l !== null && (Of(l) && uy(t.stateNode, l.stateNode), !zf(l)); )
      l = l.return;
  }
  function zf(t) {
    return t.tag === 5 || t.tag === 3 || t.tag === 27;
  }
  function Of(t) {
    return t && t.tag === 7 && t.stateNode !== null;
  }
  function Af(t) {
    var l = t.type, e = t.memoizedProps, a = t.stateNode;
    try {
      t: switch (l) {
        case "button":
        case "input":
        case "select":
        case "textarea":
          e.autoFocus && a.focus();
          break t;
        case "img":
          e.src ? a.src = e.src : e.srcSet && (a.srcset = e.srcSet);
      }
    } catch (u) {
      Et(t, t.return, u);
    }
  }
  function Mf(t, l, e) {
    try {
      var a = t.stateNode;
      Xh(a, t.type, e, l), a[vl] = l;
    } catch (u) {
      Et(t, t.return, u);
    }
  }
  function Od(t) {
    return t.tag === 5 || t.tag === 3 || t.tag === 26 || t.tag === 27 && We(t.type) || t.tag === 4;
  }
  function Cf(t) {
    t: for (; ; ) {
      for (; t.sibling === null; ) {
        if (t.return === null || Od(t.return)) return null;
        t = t.return;
      }
      for (t.sibling.return = t.return, t = t.sibling; t.tag !== 5 && t.tag !== 6 && t.tag !== 18; ) {
        if (t.tag === 27 && We(t.type) || t.flags & 2 || t.child === null || t.tag === 4) continue t;
        t.child.return = t, t = t.child;
      }
      if (!(t.flags & 2)) return t.stateNode;
    }
  }
  function Rf(t, l, e, a) {
    var u = t.tag;
    if (u === 5 || u === 6)
      u = t.stateNode, l ? (e.nodeType === 9 ? e.body : e.nodeName === "HTML" ? e.ownerDocument.body : e).insertBefore(u, l) : (l = e.nodeType === 9 ? e.body : e.nodeName === "HTML" ? e.ownerDocument.body : e, l.appendChild(u), e = e._reactRootContainer, e != null || l.onclick !== null || (l.onclick = Pl)), vi(t, a), vt = !0;
    else if (u !== 4 && (u === 27 && (vi(t, a), a = null, We(t.type) && (e = t.stateNode, l = null)), t = t.child, t !== null))
      for (Rf(
        t,
        l,
        e,
        a
      ), t = t.sibling; t !== null; )
        Rf(
          t,
          l,
          e,
          a
        ), t = t.sibling;
  }
  function hi(t, l, e, a) {
    var u = t.tag;
    if (u === 5 || u === 6)
      u = t.stateNode, l ? e.insertBefore(u, l) : e.appendChild(u), vi(t, a), vt = !0;
    else if (u !== 4 && (u === 27 && (vi(t, a), a = null, We(t.type) && (e = t.stateNode)), t = t.child, t !== null))
      for (hi(
        t,
        l,
        e,
        a
      ), t = t.sibling; t !== null; )
        hi(
          t,
          l,
          e,
          a
        ), t = t.sibling;
  }
  function Ad(t) {
    var l = t.stateNode, e = t.memoizedProps;
    try {
      for (var a = t.type, u = l.attributes; u.length; )
        l.removeAttributeNode(u[0]);
      nl(l, a, e), l[tl] = t, l[vl] = e;
    } catch (n) {
      Et(t, t.return, n);
    }
  }
  var yi = !1, zl = null;
  function Md(t) {
    (t.tag === 30 || (t.subtreeFlags & 33554432) !== 0) && (yi = !0);
  }
  var ae = null;
  function Cd() {
    var t = ae;
    return ae = null, t;
  }
  var yl = 0;
  function Wa(t, l, e, a, u) {
    return yl = 0, Rd(
      t.child,
      l,
      e,
      a,
      u
    );
  }
  function Rd(t, l, e, a, u) {
    for (var n = !1; t !== null; ) {
      if (t.tag === 5) {
        var i = t.stateNode;
        if (a !== null) {
          var c = vs(i);
          a.push(c), c.view && (n = !0);
        } else
          n || vs(i).view && (n = !0);
        yi = !0, Cm(
          i,
          yl === 0 ? l : l + "_" + yl,
          e
        ), yl++;
      } else (t.tag !== 22 || t.memoizedState === null) && (t.tag === 30 && u || Rd(
        t.child,
        l,
        e,
        a,
        u
      ) && (n = !0));
      t = t.sibling;
    }
    return n;
  }
  function ue(t, l) {
    for (; t !== null; )
      t.tag === 5 ? Rm(t.stateNode, t.memoizedProps) : (t.tag !== 22 || t.memoizedState === null) && (t.tag === 30 && l || ue(
        t.child,
        l
      )), t = t.sibling;
  }
  function gi(t) {
    if ((t.subtreeFlags & 18874368) !== 0)
      for (t = t.child; t !== null; ) {
        if ((t.tag !== 22 || t.memoizedState === null) && (gi(t), t.tag === 30 && (t.flags & 18874368) !== 0 && t.stateNode.paired)) {
          var l = t.memoizedProps;
          if (l.name == null || l.name === "auto")
            throw Error(r(544));
          var e = l.name;
          l = he(l.default, l.share), l !== "none" && (Wa(
            t,
            e,
            l,
            null,
            !1
          ) || ue(t.child, !1));
        }
        t = t.sibling;
      }
  }
  function Df(t, l) {
    if (t.tag === 30) {
      var e = t.stateNode, a = t.memoizedProps, u = ve(a, e), n = he(
        a.default,
        e.paired ? a.share : a.enter
      );
      n !== "none" ? Wa(t, u, n, null, !1) ? (gi(t), e.paired || l || uu(t, a.onEnter)) : ue(t.child, !1) : gi(t);
    } else if ((t.subtreeFlags & 33554432) !== 0)
      for (t = t.child; t !== null; )
        Df(t, l), t = t.sibling;
    else gi(t);
  }
  function Uf(t) {
    if (zl !== null && zl.size !== 0) {
      var l = zl;
      if ((t.subtreeFlags & 18874368) !== 0)
        for (t = t.child; t !== null; ) {
          if (t.tag !== 22 || t.memoizedState === null) {
            if (t.tag === 30 && (t.flags & 18874368) !== 0) {
              var e = t.memoizedProps, a = e.name;
              if (a != null && a !== "auto") {
                var u = l.get(a);
                if (u !== void 0) {
                  var n = he(
                    e.default,
                    e.share
                  );
                  if (n !== "none" && (Wa(
                    t,
                    a,
                    n,
                    null,
                    !1
                  ) ? (n = t.stateNode, u.paired = n, n.paired = u, uu(t, e.onShare)) : ue(t.child, !1)), l.delete(a), l.size === 0) break;
                }
              }
            }
            Uf(t);
          }
          t = t.sibling;
        }
    }
  }
  function jf(t) {
    if (t.tag === 30) {
      var l = t.memoizedProps, e = ve(l, t.stateNode), a = zl !== null ? zl.get(e) : void 0, u = he(
        l.default,
        a !== void 0 ? l.share : l.exit
      );
      u !== "none" && (Wa(t, e, u, null, !1) ? a !== void 0 ? (u = t.stateNode, a.paired = u, u.paired = a, zl.delete(e), uu(t, l.onShare)) : uu(t, l.onExit) : ue(t.child, !1)), zl !== null && Uf(t);
    } else if ((t.subtreeFlags & 33554432) !== 0)
      for (t = t.child; t !== null; )
        jf(t), t = t.sibling;
    else
      zl !== null && Uf(t);
  }
  function Dd(t) {
    for (t = t.child; t !== null; ) {
      if (t.tag === 30) {
        var l = t.memoizedProps, e = ve(l, t.stateNode);
        l = he(l.default, l.update), t.flags &= -5, l !== "none" && Wa(
          t,
          e,
          l,
          t.memoizedState = [],
          !1
        );
      } else
        (t.subtreeFlags & 33554432) !== 0 && Dd(t);
      t = t.sibling;
    }
  }
  function Hf(t) {
    if ((t.subtreeFlags & 18874368) !== 0)
      for (t = t.child; t !== null; ) {
        if (t.tag !== 22 || t.memoizedState === null) {
          if (t.tag === 30 && (t.flags & 18874368) !== 0) {
            var l = t.stateNode;
            l.paired !== null && (l.paired = null, ue(t.child, !1));
          }
          Hf(t);
        }
        t = t.sibling;
      }
  }
  function bi(t) {
    if (t.tag === 30)
      t.stateNode.paired = null, ue(t.child, !1), Hf(t);
    else if ((t.subtreeFlags & 33554432) !== 0)
      for (t = t.child; t !== null; )
        bi(t), t = t.sibling;
    else Hf(t);
  }
  function Ud(t) {
    for (t = t.child; t !== null; )
      t.tag === 30 ? ue(t.child, !1) : (t.subtreeFlags & 33554432) !== 0 && Ud(t), t = t.sibling;
  }
  function Bf(t, l, e, a, u, n, i) {
    for (var c = !1; l !== null; ) {
      if (l.tag === 5) {
        var f = l.stateNode;
        if (n !== null && yl < n.length) {
          var y = n[yl], S = vs(f);
          (y.view || S.view) && (c = !0);
          var z;
          if (z = (t.flags & 4) === 0)
            if (S.clip) z = !0;
            else {
              z = y.rect;
              var v = S.rect;
              z = z.y !== v.y || z.x !== v.x || z.height !== v.height || z.width !== v.width;
            }
          z && (t.flags |= 4), S.abs ? S = !y.abs : (y = y.rect, S = S.rect, S = y.height !== S.height || y.width !== S.width), S && (t.flags |= 32);
        } else t.flags |= 32;
        (t.flags & 4) !== 0 && Cm(
          f,
          yl === 0 ? e : e + "_" + yl,
          u
        ), c && (t.flags & 4) !== 0 || (ae === null && (ae = []), ae.push(
          f,
          yl === 0 ? a : a + "_" + yl,
          l.memoizedProps
        )), yl++;
      } else (l.tag !== 22 || l.memoizedState === null) && (l.tag === 30 && i ? t.flags |= l.flags & 32 : Bf(
        t,
        l.child,
        e,
        a,
        u,
        n,
        i
      ) && (c = !0));
      l = l.sibling;
    }
    return c;
  }
  function jd(t, l) {
    for (t = t.child; t !== null; ) {
      if (t.tag === 30) {
        var e = t.memoizedProps, a = t.stateNode, u = ve(e, a), n = he(e.default, e.update), i;
        i = t.memoizedState, t.memoizedState = null, a = t;
        var c = t.child;
        yl = 0, u = Bf(
          a,
          c,
          u,
          u,
          n,
          i,
          !1
        ), (t.flags & 4) !== 0 && u && uu(t, e.onUpdate);
      } else
        (t.subtreeFlags & 33554432) !== 0 && jd(t);
      t = t.sibling;
    }
  }
  var Ft = !1, bt = !1, ne = !1, qf = !1, Hd = typeof WeakSet == "function" ? WeakSet : Set, It = null, ie = !1, ku = !1, Si = !1, Yf = !1;
  function vh(t, l, e) {
    if (t = t.containerInfo, ss = vu, t = Xo(t), xc(t)) {
      if ("selectionStart" in t)
        var a = {
          start: t.selectionStart,
          end: t.selectionEnd
        };
      else
        t: {
          a = (a = t.ownerDocument) && a.defaultView || window;
          var u = a.getSelection && a.getSelection();
          if (u && u.rangeCount !== 0) {
            a = u.anchorNode;
            var n = u.anchorOffset, i = u.focusNode;
            u = u.focusOffset;
            try {
              a.nodeType, i.nodeType;
            } catch {
              a = null;
              break t;
            }
            var c = 0, f = -1, y = -1, S = 0, z = 0, v = t, b = null;
            l: for (; ; ) {
              for (var j; v !== a || n !== 0 && v.nodeType !== 3 || (f = c + n), v !== i || u !== 0 && v.nodeType !== 3 || (y = c + u), v.nodeType === 3 && (c += v.nodeValue.length), (j = v.firstChild) !== null; )
                b = v, v = j;
              for (; ; ) {
                if (v === t) break l;
                if (b === a && ++S === n && (f = c), b === i && ++z === u && (y = c), (j = v.nextSibling) !== null) break;
                v = b, b = v.parentNode;
              }
              v = j;
            }
            a = f === -1 || y === -1 ? null : { start: f, end: y };
          } else a = null;
        }
      a = a || { start: 0, end: 0 };
    } else a = null;
    for (os = { focusedElem: t, selectionRange: a }, vu = !1, e = (e & 335544064) === e, It = l, l = e ? 9270 : 1024; It !== null; ) {
      if (t = It, e && (a = t.deletions, a !== null))
        for (n = 0; n < a.length; n++)
          e && jf(a[n]);
      if (t.alternate === null && (t.flags & 2) !== 0)
        e && Md(t), pi(e);
      else {
        if (t.tag === 22) {
          if (a = t.alternate, t.memoizedState !== null) {
            a !== null && a.memoizedState === null && e && jf(a), pi(e);
            continue;
          } else if (a !== null && a.memoizedState !== null) {
            e && Md(t), pi(e);
            continue;
          }
        }
        a = t.child, (t.subtreeFlags & l) !== 0 && a !== null ? (a.return = t, It = a) : (e && Dd(t), pi(e));
      }
    }
    zl = null;
  }
  function pi(t) {
    for (; It !== null; ) {
      var l = It, e = t, a = l.alternate, u = l.flags;
      switch (l.tag) {
        case 0:
        case 11:
        case 15:
          break;
        case 1:
          if ((u & 1024) !== 0 && a !== null) {
            e = void 0, u = a.memoizedProps, a = a.memoizedState;
            var n = l.stateNode;
            try {
              var i = Sa(
                l.type,
                u
              );
              e = n.getSnapshotBeforeUpdate(
                i,
                a
              ), n.__reactInternalSnapshotBeforeUpdate = e;
            } catch (c) {
              Et(l, l.return, c);
            }
          }
          break;
        case 3:
          if ((u & 1024) !== 0) {
            if (a = l.stateNode.containerInfo, e = a.nodeType, e === 9)
              gs(a);
            else if (e === 1)
              switch (a.nodeName) {
                case "HEAD":
                case "HTML":
                case "BODY":
                  gs(a);
                  break;
                default:
                  a.textContent = "";
              }
          }
          break;
        case 5:
        case 26:
        case 27:
        case 6:
        case 4:
        case 17:
          break;
        case 30:
          e && a !== null && (e = ve(
            a.memoizedProps,
            a.stateNode
          ), u = l.memoizedProps, u = he(u.default, u.update), u !== "none" && Wa(
            a,
            e,
            u,
            a.memoizedState = [],
            !0
          ));
          break;
        default:
          if ((u & 1024) !== 0) throw Error(r(163));
      }
      if (a = l.sibling, a !== null) {
        a.return = l.return, It = a;
        break;
      }
      It = l.return;
    }
  }
  function Bd(t, l, e) {
    var a = e.flags;
    switch (e.tag) {
      case 0:
      case 11:
      case 15:
        ce(t, e), a & 4 && Ku(5, e);
        break;
      case 1:
        if (ce(t, e), a & 4)
          if (t = e.stateNode, l === null)
            try {
              t.componentDidMount();
            } catch (i) {
              Et(e, e.return, i);
            }
          else {
            var u = Sa(
              e.type,
              l.memoizedProps
            );
            l = l.memoizedState;
            try {
              t.componentDidUpdate(
                u,
                l,
                t.__reactInternalSnapshotBeforeUpdate
              );
            } catch (i) {
              Et(
                e,
                e.return,
                i
              );
            }
          }
        a & 64 && Ed(e), a & 512 && ee(e, e.return);
        break;
      case 3:
        if (ce(t, e), a & 64 && (t = e.updateQueue, t !== null)) {
          if (l = null, e.child !== null)
            switch (e.child.tag) {
              case 27:
              case 5:
                l = e.child.stateNode;
                break;
              case 1:
                l = e.child.stateNode;
            }
          try {
            mr(t, l);
          } catch (i) {
            Et(e, e.return, i);
          }
        }
        break;
      case 27:
        l === null && a & 4 && Ad(e);
      case 26:
      case 5:
        ce(t, e), l === null && a & 4 && Af(e), a & 512 && ee(e, e.return);
        break;
      case 12:
        ce(t, e);
        break;
      case 31:
        ce(t, e), a & 4 && Gd(t, e);
        break;
      case 13:
        ce(t, e), a & 4 && Qd(t, e), a & 64 && (t = e.memoizedState, t !== null && (t = t.dehydrated, t !== null && (e = zh.bind(
          null,
          e
        ), cy(t, e))));
        break;
      case 22:
        if (a = e.memoizedState !== null || Ft, !a) {
          var n = l !== null && l.memoizedState !== null || bt;
          l = Ft, u = bt, Ft = a, (bt = n) && !u ? (a = 2, (e.subtreeFlags & 8772) !== 0 && (a |= 1), kl(
            t,
            e,
            a
          )) : ce(t, e), Ft = l, bt = u;
        }
        break;
      case 30:
        ce(t, e), a & 512 && ee(e, e.return);
        break;
      case 7:
        a & 512 && ee(e, e.return);
      default:
        ce(t, e);
    }
  }
  function Xf(t, l) {
    for (t = t.child; t !== null; )
      qd(t, l), t = t.sibling;
  }
  function qd(t, l) {
    switch (t.tag) {
      case 5:
      case 26:
        try {
          var e = t.stateNode;
          if (l) {
            var a = e.style;
            typeof a.setProperty == "function" ? a.setProperty("display", "none", "important") : a.display = "none";
          } else {
            var u = t.stateNode, n = t.memoizedProps.style, i = n != null && n.hasOwnProperty("display") ? n.display : null;
            u.style.display = i == null || typeof i == "boolean" ? "" : ("" + i).trim();
          }
        } catch (f) {
          Et(t, t.return, f);
        }
        Gf(t, l);
        break;
      case 6:
        try {
          t.stateNode.nodeValue = l ? "" : t.memoizedProps, vt = !0;
        } catch (f) {
          Et(t, t.return, f);
        }
        break;
      case 18:
        try {
          var c = t.stateNode;
          l ? Mm(c, !0) : Mm(t.stateNode, !1);
        } catch (f) {
          Et(t, t.return, f);
        }
        break;
      case 22:
      case 23:
        t.memoizedState === null && Xf(t, l);
        break;
      default:
        Xf(t, l);
    }
  }
  function Gf(t, l) {
    if (t.subtreeFlags & 67108864)
      for (t = t.child; t !== null; ) {
        t: {
          var e = t, a = l;
          switch (e.tag) {
            case 4:
              qd(e, a);
              break t;
            case 22:
              e.memoizedState === null && Gf(e, a);
              break t;
            default:
              Gf(e, a);
          }
        }
        t = t.sibling;
      }
  }
  function Yd(t) {
    var l = t.alternate;
    l !== null && (t.alternate = null, Yd(l)), t.child = null, t.deletions = null, t.sibling = null, t.tag === 5 && (l = t.stateNode, l !== null && Nn(l)), t.stateNode = null, t.return = null, t.dependencies = null, t.memoizedProps = null, t.memoizedState = null, t.pendingProps = null, t.stateNode = null, t.updateQueue = null;
  }
  var jt = null, gl = !1;
  function Kl(t, l, e) {
    for (e = e.child; e !== null; )
      Xd(t, l, e), e = e.sibling;
  }
  function Xd(t, l, e) {
    if (_l && typeof _l.onCommitFiberUnmount == "function")
      try {
        _l.onCommitFiberUnmount(gu, e);
      } catch {
      }
    switch (e.tag) {
      case 26:
        bt || ul(e, l), Kl(
          t,
          l,
          e
        ), e.memoizedState ? e.memoizedState.count-- : e.stateNode && !bt && (e = e.stateNode, e.parentNode.removeChild(e));
        break;
      case 27:
        bt || ul(e, l), Ju(e);
        var a = jt, u = gl;
        We(e.type) && (jt = e.stateNode, gl = !1), Kl(
          t,
          l,
          e
        ), Zm(
          e.stateNode,
          e.type,
          e.memoizedProps
        ), jt = a, gl = u;
        break;
      case 5:
        bt || ul(e, l), Ju(e);
      case 6:
        if (e.tag === 6 && Ju(e), a = jt, u = gl, jt = null, Kl(
          t,
          l,
          e
        ), jt = a, gl = u, jt !== null)
          if (gl)
            try {
              (jt.nodeType === 9 ? jt.body : jt.nodeName === "HTML" ? jt.ownerDocument.body : jt).removeChild(e.stateNode), vt = !0;
            } catch (n) {
              Et(
                e,
                l,
                n
              );
            }
          else
            try {
              jt.removeChild(e.stateNode), vt = !0;
            } catch (n) {
              Et(
                e,
                l,
                n
              );
            }
        break;
      case 18:
        jt !== null && (gl ? (t = jt, Am(
          t.nodeType === 9 ? t.body : t.nodeName === "HTML" ? t.ownerDocument.body : t,
          e.stateNode
        ), hu(t)) : Am(jt, e.stateNode));
        break;
      case 4:
        a = jt, u = gl, jt = e.stateNode.containerInfo, gl = !0, Kl(
          t,
          l,
          e
        ), jt = a, gl = u;
        break;
      case 0:
      case 11:
      case 14:
      case 15:
        Ze(2, e, l), bt || Ze(4, e, l), Kl(
          t,
          l,
          e
        );
        break;
      case 1:
        bt || (ul(e, l), a = e.stateNode, typeof a.componentWillUnmount == "function" && Nd(
          e,
          l,
          a
        )), Kl(
          t,
          l,
          e
        );
        break;
      case 21:
        Kl(
          t,
          l,
          e
        );
        break;
      case 22:
        bt = (a = bt) || e.memoizedState !== null, Kl(
          t,
          l,
          e
        ), bt = a;
        break;
      case 30:
        ul(e, l), Kl(
          t,
          l,
          e
        );
        break;
      case 7:
        bt || ul(e, l), Kl(
          t,
          l,
          e
        );
        break;
      default:
        Kl(
          t,
          l,
          e
        );
    }
  }
  function Gd(t, l) {
    if (l.memoizedState === null && (t = l.alternate, t !== null && (t = t.memoizedState, t !== null))) {
      t = t.dehydrated;
      try {
        hu(t);
      } catch (e) {
        Et(l, l.return, e);
      }
    }
  }
  function Qd(t, l) {
    if (l.memoizedState === null && (t = l.alternate, t !== null && (t = t.memoizedState, t !== null && (t = t.dehydrated, t !== null))))
      try {
        hu(t);
      } catch (e) {
        Et(l, l.return, e);
      }
  }
  function hh(t) {
    switch (t.tag) {
      case 31:
      case 13:
      case 19:
        var l = t.stateNode;
        return l === null && (l = t.stateNode = new Hd()), l;
      case 22:
        return t = t.stateNode, l = t._retryCache, l === null && (l = t._retryCache = new Hd()), l;
      default:
        throw Error(r(435, t.tag));
    }
  }
  function _i(t, l) {
    var e = hh(t);
    l.forEach(function(a) {
      if (!e.has(a)) {
        e.add(a);
        var u = Oh.bind(null, t, a);
        a.then(u, u);
      }
    });
  }
  function dl(t, l, e) {
    var a = l.deletions;
    if (a !== null)
      for (var u = 0; u < a.length; u++) {
        var n = a[u], i = t, c = l, f = c;
        t: for (; f !== null; ) {
          switch (f.tag) {
            case 27:
              if (We(f.type)) {
                jt = f.stateNode, gl = !1;
                break t;
              }
              break;
            case 5:
              jt = f.stateNode, gl = !1;
              break t;
            case 3:
            case 4:
              jt = f.stateNode.containerInfo, gl = !0;
              break t;
          }
          f = f.return;
        }
        if (jt === null) throw Error(r(160));
        Xd(i, c, n), jt = null, gl = !1, i = n.alternate, i !== null && (i.return = null), n.return = null;
      }
    if (l.subtreeFlags & 13886)
      for (l = l.child; l !== null; )
        Ld(l, t, e), l = l.sibling;
  }
  var Jl = null;
  function Ld(t, l, e) {
    var a = t.alternate, u = t.flags;
    switch (t.tag) {
      case 0:
      case 11:
      case 14:
      case 15:
        if (u & 4 && (a = t.updateQueue, a = a !== null ? a.events : null, a !== null))
          for (var n = 0; n < a.length; n++) {
            var i = a[n];
            i.ref.impl = i.nextImpl;
          }
        dl(l, t, e), ml(t), u & 4 && (Ze(3, t, t.return), Ku(3, t), Ze(5, t, t.return));
        break;
      case 1:
        dl(l, t, e), ml(t), u & 512 && (bt || a === null || ul(a, a.return)), u & 64 && Ft && (t = t.updateQueue, t !== null && (l = t.callbacks, l !== null && (e = t.shared.hiddenCallbacks, t.shared.hiddenCallbacks = e === null ? l : e.concat(l))));
        break;
      case 26:
        if (n = Jl, dl(l, t, e), ml(t), u & 512 && (bt || a === null || ul(a, a.return)), u & 4)
          if (u = a !== null ? a.memoizedState : null, e = t.memoizedState, a === null)
            if (e === null)
              if (t.stateNode === null)
                if (Ft)
                  t.stateNode = Nm(
                    t.type,
                    t.memoizedProps,
                    l.containerInfo,
                    t
                  );
                else {
                  t: {
                    l = t.type, e = t.memoizedProps, u = n.ownerDocument || n;
                    l: switch (l) {
                      case "title":
                        a = u.getElementsByTagName("title")[0], (!a || a[pu] || a[tl] || a.namespaceURI === "http://www.w3.org/2000/svg" || a.hasAttribute("itemprop")) && (a = u.createElement(l), u.head.insertBefore(
                          a,
                          u.querySelector("head > title")
                        )), nl(a, l, e), a[tl] = t, $t(a), l = a;
                        break t;
                      case "link":
                        if (n = $m(
                          "link",
                          "href",
                          u
                        ).get(l + (e.href || ""))) {
                          for (i = 0; i < n.length; i++)
                            if (a = n[i], a.getAttribute("href") === (e.href == null || e.href === "" ? null : e.href) && a.getAttribute("rel") === (e.rel == null ? null : e.rel) && a.getAttribute("title") === (e.title == null ? null : e.title) && a.getAttribute("crossorigin") === (e.crossOrigin == null ? null : e.crossOrigin)) {
                              n.splice(i, 1);
                              break l;
                            }
                        }
                        a = u.createElement(l), nl(a, l, e), u.head.appendChild(a);
                        break;
                      case "meta":
                        if (n = $m(
                          "meta",
                          "content",
                          u
                        ).get(l + (e.content || ""))) {
                          for (i = 0; i < n.length; i++)
                            if (a = n[i], a.getAttribute("content") === (e.content == null ? null : "" + e.content) && a.getAttribute("name") === (e.name == null ? null : e.name) && a.getAttribute("property") === (e.property == null ? null : e.property) && a.getAttribute("http-equiv") === (e.httpEquiv == null ? null : e.httpEquiv) && a.getAttribute("charset") === (e.charSet == null ? null : e.charSet)) {
                              n.splice(i, 1);
                              break l;
                            }
                        }
                        a = u.createElement(l), nl(a, l, e), u.head.appendChild(a);
                        break;
                      default:
                        throw Error(r(468, l));
                    }
                    a[tl] = t, $t(a), l = a;
                  }
                  t.stateNode = l;
                }
              else
                Ft || Es(n, t.type, t.stateNode);
            else
              t.stateNode = km(
                n,
                e,
                t.memoizedProps
              );
          else
            u !== e ? (u === null ? (l = a.stateNode, l === null || bt || l.parentNode.removeChild(l)) : u.count--, e === null ? Ft || Es(n, t.type, t.stateNode) : km(n, e, t.memoizedProps)) : e === null && t.stateNode !== null && Mf(
              t,
              t.memoizedProps,
              a.memoizedProps
            );
        break;
      case 27:
        dl(l, t, e), ml(t), u & 512 && (bt || a === null || ul(a, a.return)), a !== null && u & 4 && Mf(
          t,
          t.memoizedProps,
          a.memoizedProps
        );
        break;
      case 5:
        if (n = ne, ne = !1, dl(l, t, e), ne = n, ml(t), u & 512 && (bt || a === null || ul(a, a.return)), t.flags & 32) {
          l = t.stateNode;
          try {
            Da(l, ""), vt = !0;
          } catch (S) {
            Et(t, t.return, S);
          }
        }
        u & 4 && t.stateNode != null && (l = t.memoizedProps, Mf(
          t,
          l,
          a !== null ? a.memoizedProps : l
        )), u & 1024 && (qf = !0);
        break;
      case 6:
        if (dl(l, t, e), ml(t), u & 4) {
          if (t.stateNode === null)
            throw Error(r(162));
          l = t.memoizedProps, e = t.stateNode;
          try {
            e.nodeValue = l, vt = !0;
          } catch (S) {
            Et(t, t.return, S);
          }
        }
        break;
      case 3:
        if (vt = !1, Bi = null, n = Jl, Jl = an(l.containerInfo), dl(l, t, e), Jl = n, ml(t), u & 4 && a !== null && a.memoizedState.isDehydrated)
          try {
            hu(l.containerInfo);
          } catch (S) {
            Et(t, t.return, S);
          }
        qf && (qf = !1, Zd(t)), vt = !1;
        break;
      case 4:
        u = ne, ne = Ft, a = fo(), n = Jl, Jl = an(
          t.stateNode.containerInfo
        ), dl(l, t, e), ml(t), Jl = n, vt && ku && (Si = !0), vt = a, ne = u;
        break;
      case 12:
        dl(l, t, e), ml(t);
        break;
      case 31:
        dl(l, t, e), ml(t), u & 4 && (l = t.updateQueue, l !== null && (t.updateQueue = null, _i(t, l)));
        break;
      case 13:
        dl(l, t, e), ml(t), t.child.flags & 8192 && t.memoizedState !== null != (a !== null && a.memoizedState !== null) && (Ei = pl()), u & 4 && (l = t.updateQueue, l !== null && (t.updateQueue = null, _i(t, l)));
        break;
      case 22:
        n = t.memoizedState !== null, i = a !== null && a.memoizedState !== null;
        var c = Ft, f = bt, y = ne;
        Ft = c || n, ne = y || n, bt = f || i, dl(l, t, e), bt = f, ne = y, Ft = c, ml(t), u & 8192 && (l = t.stateNode, l._visibility = n ? l._visibility & -2 : l._visibility | 1, !n || a === null || i || Ft || bt || (l = i || bt, e = Ft, a = bt, Ft = n || Ft, bt = l, we(t, 2), Ft = e, bt = a), !n && ne || Xf(t, n)), u & 4 && (l = t.updateQueue, l !== null && (e = l.retryQueue, e !== null && (l.retryQueue = null, _i(t, e))));
        break;
      case 19:
        dl(l, t, e), ml(t), u & 4 && (l = t.updateQueue, l !== null && (t.updateQueue = null, _i(t, l)));
        break;
      case 30:
        u & 512 && (bt || a === null || ul(a, a.return)), u = fo(), n = ku, i = (e & 335544064) === e, c = t.memoizedProps, ku = i && he(
          c.default,
          c.update
        ) !== "none", dl(l, t, e), ml(t), i && a !== null && vt && (t.flags |= 4), ku = n, vt = u;
        break;
      case 21:
        break;
      case 7:
        u & 512 && (bt || a === null || ul(a, a.return)), a && a.stateNode !== null && (a.stateNode._fragmentFiber = t);
      default:
        dl(l, t, e), ml(t);
    }
  }
  function ml(t) {
    var l = t.flags;
    if (l & 2) {
      try {
        for (var e, a = t.return; a !== null; ) {
          if (Od(a)) {
            e = a;
            break;
          }
          a = a.return;
        }
        a = null;
        for (var u = t.return; u !== null; ) {
          if (Of(u)) {
            var n = u.stateNode;
            a === null ? a = [n] : a.push(n);
          }
          if (zf(u)) break;
          u = u.return;
        }
        var i = a;
        if (e == null) throw Error(r(160));
        switch (e.tag) {
          case 27:
            var c = e.stateNode, f = Cf(t);
            hi(
              t,
              f,
              c,
              i
            );
            break;
          case 5:
            var y = e.stateNode;
            e.flags & 32 && (Da(y, ""), e.flags &= -33);
            var S = Cf(t);
            hi(
              t,
              S,
              y,
              i
            );
            break;
          case 3:
          case 4:
            var z = e.stateNode.containerInfo, v = Cf(t);
            Rf(
              t,
              v,
              z,
              i
            );
            break;
          default:
            throw Error(r(161));
        }
      } catch (b) {
        Et(t, t.return, b);
      }
      t.flags &= -3;
    }
    l & 4096 && (t.flags &= -4097);
  }
  function Zd(t) {
    if (t.subtreeFlags & 1024)
      for (t = t.child; t !== null; ) {
        var l = t;
        Zd(l), l.tag === 5 && l.flags & 1024 && (l = l.stateNode, vu = !0, l.reset(), vu = !1), t = t.sibling;
      }
  }
  function Fa(t, l) {
    if (l.subtreeFlags & 9270)
      for (l = l.child; l !== null; )
        wd(l, t), l = l.sibling;
    else jd(l);
  }
  function wd(t, l) {
    var e = t.alternate;
    if (e === null) Df(t, !1);
    else
      switch (t.tag) {
        case 3:
          if (Yf = ie = !1, Cd(), Fa(l, t), !ie && !Si) {
            if (t = ae, t !== null)
              for (var a = 0; a < t.length; a += 3) {
                e = t[a];
                var u = t[a + 1];
                Rm(e, t[a + 2]), e = e.ownerDocument.documentElement, e !== null && e.animate(
                  { opacity: [0, 0], pointerEvents: ["none", "none"] },
                  {
                    duration: 0,
                    fill: "forwards",
                    pseudoElement: "::view-transition-group(" + u + ")"
                  }
                );
              }
            t = l.containerInfo, t = t.nodeType === 9 ? t.documentElement : t.ownerDocument.documentElement, t !== null && t.style.viewTransitionName === "" && (t.style.viewTransitionName = "none", t.animate(
              { opacity: [0, 0], pointerEvents: ["none", "none"] },
              {
                duration: 0,
                fill: "forwards",
                pseudoElement: "::view-transition-group(root)"
              }
            ), t.animate(
              { width: [0, 0], height: [0, 0] },
              {
                duration: 0,
                fill: "forwards",
                pseudoElement: "::view-transition"
              }
            )), Yf = !0;
          }
          ae = null;
          break;
        case 5:
          Fa(l, t);
          break;
        case 4:
          a = ie, ie = !1, Fa(l, t), ie && (Si = !0), ie = a;
          break;
        case 22:
          t.memoizedState === null && (e.memoizedState !== null ? Df(t, !1) : Fa(l, t));
          break;
        case 30:
          a = ie, u = Cd(), ie = !1, Fa(l, t), ie && (t.flags |= 4);
          var n = t.memoizedProps, i = t.stateNode;
          l = ve(n, i), i = ve(e.memoizedProps, i);
          var c = he(n.default, n.update);
          c === "none" ? l = !1 : (n = e.memoizedState, e.memoizedState = null, e = t.child, yl = 0, l = Bf(
            t,
            e,
            l,
            i,
            c,
            n,
            !0
          ), yl !== (n === null ? 0 : n.length) && (t.flags |= 32)), (t.flags & 4) !== 0 && l ? (uu(
            t,
            t.memoizedProps.onUpdate
          ), ae = u) : u !== null && (u.push.apply(u, ae), ae = u), ie = (t.flags & 32) !== 0 ? !0 : a;
          break;
        default:
          Fa(l, t);
      }
  }
  function ce(t, l) {
    if (l.subtreeFlags & 8772)
      for (l = l.child; l !== null; )
        Bd(t, l.alternate, l), l = l.sibling;
  }
  function we(t, l) {
    for (t = t.child; t !== null; ) {
      var e = t, a = l;
      switch (e.tag) {
        case 0:
        case 11:
        case 14:
        case 15:
          Ze(4, e, e.return), we(
            e,
            a
          );
          break;
        case 1:
          ul(e, e.return);
          var u = e.stateNode;
          typeof u.componentWillUnmount == "function" && Nd(
            e,
            e.return,
            u
          ), we(
            e,
            a
          );
          break;
        case 27:
          (a & 2) !== 0 && Zm(
            e.stateNode,
            e.type,
            e.memoizedProps
          );
        case 5:
          ul(e, e.return), e.tag !== 5 && e.tag !== 27 || Ju(e), we(
            e,
            a
          );
          break;
        case 6:
          Ju(e);
          break;
        case 26:
          ul(e, e.return), u = e.stateNode, e.memoizedState !== null || u === null || bt || u.parentNode.removeChild(u), we(
            e,
            a
          );
          break;
        case 22:
          e.memoizedState === null && we(
            e,
            a
          );
          break;
        case 30:
          ul(e, e.return), we(
            e,
            a
          );
          break;
        case 7:
          ul(e, e.return);
        default:
          we(
            e,
            a
          );
      }
      t = t.sibling;
    }
  }
  function kl(t, l, e) {
    for (e = (l.subtreeFlags & 8772) !== 0 ? e : e & -2, l = l.child; l !== null; ) {
      var a = l.alternate, u = t, n = l, i = n.flags, c = (e & 1) !== 0;
      switch (n.tag) {
        case 0:
        case 11:
        case 15:
          kl(
            u,
            n,
            e
          ), Ku(4, n);
          break;
        case 1:
          if (kl(
            u,
            n,
            e
          ), a = n, u = a.stateNode, typeof u.componentDidMount == "function")
            try {
              u.componentDidMount();
            } catch (S) {
              Et(a, a.return, S);
            }
          if (a = n, u = a.updateQueue, u !== null) {
            var f = a.stateNode;
            try {
              var y = u.shared.hiddenCallbacks;
              if (y !== null)
                for (u.shared.hiddenCallbacks = null, u = 0; u < y.length; u++)
                  dr(y[u], f);
            } catch (S) {
              Et(a, a.return, S);
            }
          }
          c && i & 64 && Ed(n), ee(n, n.return);
          break;
        case 27:
          (e & 2) !== 0 && Ad(n);
        case 5:
          n.tag !== 5 && n.tag !== 27 || zd(n), kl(
            u,
            n,
            e
          ), c && a === null && i & 4 && Af(n), ee(n, n.return);
          break;
        case 6:
          zd(n);
          break;
        case 26:
          f = n.stateNode, n.memoizedState !== null || f === null || Ft || Es(
            an(f.ownerDocument),
            n.type,
            f
          ), kl(
            u,
            n,
            e
          ), c && a === null && i & 4 && Af(n), ee(n, n.return);
          break;
        case 12:
          kl(
            u,
            n,
            e
          );
          break;
        case 31:
          kl(
            u,
            n,
            e
          ), c && i & 4 && Gd(u, n);
          break;
        case 13:
          kl(
            u,
            n,
            e
          ), c && i & 4 && Qd(u, n);
          break;
        case 22:
          n.memoizedState === null && kl(
            u,
            n,
            e
          ), ee(n, n.return);
          break;
        case 30:
          kl(
            u,
            n,
            e
          ), ee(n, n.return);
          break;
        case 7:
          ee(n, n.return);
        default:
          kl(
            u,
            n,
            e
          );
      }
      l = l.sibling;
    }
  }
  function Qf(t, l) {
    var e = null;
    t !== null && t.memoizedState !== null && t.memoizedState.cachePool !== null && (e = t.memoizedState.cachePool.pool), t = null, l.memoizedState !== null && l.memoizedState.cachePool !== null && (t = l.memoizedState.cachePool.pool), t !== e && (t != null && t.refCount++, e != null && Uu(e));
  }
  function Lf(t, l) {
    t = null, l.alternate !== null && (t = l.alternate.memoizedState.cache), l = l.memoizedState.cache, l !== t && (l.refCount++, t != null && Uu(t));
  }
  function Xl(t, l, e, a) {
    var u = (e & 335544064) === e;
    if (l.subtreeFlags & (u ? 10262 : 10256))
      for (l = l.child; l !== null; )
        Vd(
          t,
          l,
          e,
          a
        ), l = l.sibling;
    else u && Ud(l);
  }
  function Vd(t, l, e, a) {
    var u = (e & 335544064) === e;
    u && l.alternate === null && l.return !== null && l.return.alternate !== null && bi(l);
    var n = l.flags;
    switch (l.tag) {
      case 0:
      case 11:
      case 15:
        Xl(
          t,
          l,
          e,
          a
        ), n & 2048 && Ku(9, l);
        break;
      case 1:
        Xl(
          t,
          l,
          e,
          a
        );
        break;
      case 3:
        Xl(
          t,
          l,
          e,
          a
        ), u && Yf && (t = t.containerInfo, t = t.nodeType === 9 ? t.body : t.nodeName === "HTML" ? t.ownerDocument.body : t, t.style.viewTransitionName === "root" && (t.style.viewTransitionName = ""), t = t.ownerDocument.documentElement, t !== null && t.style.viewTransitionName === "none" && (t.style.viewTransitionName = "")), n & 2048 && (n = null, l.alternate !== null && (n = l.alternate.memoizedState.cache), l = l.memoizedState.cache, l !== n && (l.refCount++, n != null && Uu(n)));
        break;
      case 12:
        if (n & 2048) {
          Xl(
            t,
            l,
            e,
            a
          ), n = l.stateNode;
          try {
            var i = l.memoizedProps, c = i.id, f = i.onPostCommit;
            typeof f == "function" && f(
              c,
              l.alternate === null ? "mount" : "update",
              n.passiveEffectDuration,
              -0
            );
          } catch (y) {
            Et(l, l.return, y);
          }
        } else
          Xl(
            t,
            l,
            e,
            a
          );
        break;
      case 31:
        Xl(
          t,
          l,
          e,
          a
        );
        break;
      case 13:
        Xl(
          t,
          l,
          e,
          a
        );
        break;
      case 23:
        break;
      case 22:
        i = l.stateNode, c = l.alternate, l.memoizedState !== null ? (u && c !== null && c.memoizedState === null && bi(c), i._visibility & 2 ? Xl(
          t,
          l,
          e,
          a
        ) : $u(
          t,
          l
        )) : (u && c !== null && c.memoizedState !== null && bi(l), i._visibility & 2 ? Xl(
          t,
          l,
          e,
          a
        ) : (i._visibility |= 2, Ia(
          t,
          l,
          e,
          a,
          (l.subtreeFlags & 10256) !== 0 || !1
        ))), n & 2048 && Qf(c, l);
        break;
      case 24:
        Xl(
          t,
          l,
          e,
          a
        ), n & 2048 && Lf(l.alternate, l);
        break;
      case 30:
        u && (n = l.alternate, n !== null && (ue(n.child, !0), ue(l.child, !0))), Xl(
          t,
          l,
          e,
          a
        );
        break;
      default:
        Xl(
          t,
          l,
          e,
          a
        );
    }
  }
  function Ia(t, l, e, a, u) {
    for (u = u && ((l.subtreeFlags & 10256) !== 0 || !1), l = l.child; l !== null; ) {
      var n = t, i = l, c = e, f = a, y = i.flags;
      switch (i.tag) {
        case 0:
        case 11:
        case 15:
          Ia(
            n,
            i,
            c,
            f,
            u
          ), Ku(8, i);
          break;
        case 23:
          break;
        case 22:
          var S = i.stateNode;
          i.memoizedState !== null ? S._visibility & 2 ? Ia(
            n,
            i,
            c,
            f,
            u
          ) : $u(
            n,
            i
          ) : (S._visibility |= 2, Ia(
            n,
            i,
            c,
            f,
            u
          )), u && y & 2048 && Qf(
            i.alternate,
            i
          );
          break;
        case 24:
          Ia(
            n,
            i,
            c,
            f,
            u
          ), u && y & 2048 && Lf(i.alternate, i);
          break;
        default:
          Ia(
            n,
            i,
            c,
            f,
            u
          );
      }
      l = l.sibling;
    }
  }
  function $u(t, l) {
    if (l.subtreeFlags & 10256)
      for (l = l.child; l !== null; ) {
        var e = t, a = l, u = a.flags;
        switch (a.tag) {
          case 22:
            $u(e, a), u & 2048 && Qf(
              a.alternate,
              a
            );
            break;
          case 24:
            $u(e, a), u & 2048 && Lf(a.alternate, a);
            break;
          default:
            $u(e, a);
        }
        l = l.sibling;
      }
  }
  var pa = 8192;
  function _a(t, l, e) {
    if (t.subtreeFlags & pa)
      for (t = t.child; t !== null; )
        Kd(
          t,
          l,
          e
        ), t = t.sibling;
  }
  function Kd(t, l, e) {
    switch (t.tag) {
      case 26:
        _a(
          t,
          l,
          e
        ), t.flags & pa && (t.memoizedState !== null ? _y(
          e,
          Jl,
          t.memoizedState,
          t.memoizedProps
        ) : (t = t.stateNode, (l & 335544128) === l && Pm(e, t)));
        break;
      case 5:
        _a(
          t,
          l,
          e
        ), t.flags & pa && (t = t.stateNode, (l & 335544128) === l && Pm(e, t));
        break;
      case 3:
      case 4:
        var a = Jl;
        Jl = an(t.stateNode.containerInfo), _a(
          t,
          l,
          e
        ), Jl = a;
        break;
      case 22:
        t.memoizedState === null && (a = t.alternate, a !== null && a.memoizedState !== null ? (a = pa, pa = 16777216, _a(
          t,
          l,
          e
        ), pa = a) : _a(
          t,
          l,
          e
        ));
        break;
      case 30:
        if ((t.flags & pa) !== 0 && (a = t.memoizedProps.name, a != null && a !== "auto")) {
          var u = t.stateNode;
          u.paired = null, zl === null && (zl = /* @__PURE__ */ new Map()), zl.set(a, u);
        }
        _a(
          t,
          l,
          e
        );
        break;
      default:
        _a(
          t,
          l,
          e
        );
    }
  }
  function Jd(t) {
    var l = t.alternate;
    if (l !== null && (t = l.child, t !== null)) {
      l.child = null;
      do
        l = t.sibling, t.sibling = null, t = l;
      while (t !== null);
    }
  }
  function Wu(t) {
    var l = t.deletions;
    if ((t.flags & 16) !== 0) {
      if (l !== null)
        for (var e = 0; e < l.length; e++) {
          var a = l[e];
          It = a, $d(
            a,
            t
          );
        }
      Jd(t);
    }
    if (t.subtreeFlags & 10256)
      for (t = t.child; t !== null; )
        kd(t), t = t.sibling;
  }
  function kd(t) {
    switch (t.tag) {
      case 0:
      case 11:
      case 15:
        Wu(t), t.flags & 2048 && Ze(9, t, t.return);
        break;
      case 3:
        Wu(t);
        break;
      case 12:
        Wu(t);
        break;
      case 22:
        var l = t.stateNode;
        t.memoizedState !== null && l._visibility & 2 && (t.return === null || t.return.tag !== 13) ? (l._visibility &= -3, Ti(t)) : Wu(t);
        break;
      default:
        Wu(t);
    }
  }
  function Ti(t) {
    var l = t.deletions;
    if ((t.flags & 16) !== 0) {
      if (l !== null)
        for (var e = 0; e < l.length; e++) {
          var a = l[e];
          It = a, $d(
            a,
            t
          );
        }
      Jd(t);
    }
    for (t = t.child; t !== null; ) {
      switch (l = t, l.tag) {
        case 0:
        case 11:
        case 15:
          Ze(8, l, l.return), Ti(l);
          break;
        case 22:
          e = l.stateNode, e._visibility & 2 && (e._visibility &= -3, Ti(l));
          break;
        default:
          Ti(l);
      }
      t = t.sibling;
    }
  }
  function $d(t, l) {
    for (; It !== null; ) {
      var e = It;
      switch (e.tag) {
        case 0:
        case 11:
        case 15:
          Ze(8, e, l);
          break;
        case 23:
        case 22:
          if (e.memoizedState !== null && e.memoizedState.cachePool !== null) {
            var a = e.memoizedState.cachePool.pool;
            a != null && a.refCount++;
          }
          break;
        case 24:
          Uu(e.memoizedState.cache);
      }
      if (a = e.child, a !== null) a.return = e, It = a;
      else
        t: for (e = t; It !== null; ) {
          a = It;
          var u = a.sibling, n = a.return;
          if (Yd(a), a === e) {
            It = null;
            break t;
          }
          if (u !== null) {
            u.return = n, It = u;
            break t;
          }
          It = n;
        }
    }
  }
  var yh = {
    getCacheForType: function(t) {
      var l = ll(Zt), e = l.data.get(t);
      return e === void 0 && (e = t(), l.data.set(t, e)), e;
    },
    cacheSignal: function() {
      return ll(Zt).controller.signal;
    }
  }, gh = typeof WeakMap == "function" ? WeakMap : Map, yt = 0, At = null, ft = null, ot = 0, xt = 0, Ol = null, Ve = !1, Pa = !1, Zf = !1, Ee = 0, Gt = 0, Ke = 0, Ta = 0, xi = 0, Al = 0, tu = 0, Fu = null, bl = null, wf = !1, Ei = 0, Wd = 0, Ni = 1 / 0, zi = null, Je = null, Bt = 0, $l = null, xa = null, fe = 0, Vf = 0, Kf = null, Fd = null, lu = null, eu = null, au = null, Iu = 0, Oi = null;
  function Ml() {
    return (yt & 2) !== 0 && ot !== 0 ? ot & -ot : H.T !== null ? es() : Ps();
  }
  function Id() {
    if (Al === 0)
      if ((ot & 536870912) === 0 || ct) {
        var t = _n;
        _n <<= 1, (_n & 3932160) === 0 && (_n = 262144), Al = t;
      } else Al = 536870912;
    return t = el.current, t !== null && (t.flags |= 32), Al;
  }
  function uu(t, l) {
    if (l != null) {
      var e = t.stateNode, a = e.ref;
      a === null && (a = e.ref = Dm(
        ve(t.memoizedProps, e)
      )), eu === null && (eu = []), eu.push(l.bind(null, a));
    }
  }
  function Sl(t, l, e) {
    (t === At && (xt === 2 || xt === 9) || t.cancelPendingCommit !== null) && (nu(t, 0), ke(
      t,
      ot,
      Al,
      !1
    )), Su(t, e), ((yt & 2) === 0 || t !== At) && (t === At && ((yt & 2) === 0 && (Ta |= e), Gt === 4 && ke(
      t,
      ot,
      Al,
      !1
    )), se(t));
  }
  function Pd(t, l, e) {
    if ((yt & 6) !== 0) throw Error(r(327));
    var a = !e && (l & 127) === 0 && (l & t.expiredLanes) === 0 || bu(t, l), u = a ? ph(t, l) : kf(t, l, !0), n = a;
    do {
      if (u === 0) {
        Pa && !a && ke(t, l, 0, !1);
        break;
      } else {
        if (e = t.current.alternate, n && !bh(e)) {
          u = kf(t, l, !1), n = !1;
          continue;
        }
        if (u === 2) {
          if (n = l, t.errorRecoveryDisabledLanes & n)
            var i = 0;
          else
            i = t.pendingLanes & -536870913, i = i !== 0 ? i : i & 536870912 ? 536870912 : 0;
          if (i !== 0) {
            l = i;
            t: {
              var c = t;
              u = Fu;
              var f = c.current.memoizedState.isDehydrated;
              if (f && (nu(c, i).flags |= 256), i = kf(
                c,
                i,
                !1
              ), i !== 2 && i !== 6) {
                if (Zf && !f) {
                  c.errorRecoveryDisabledLanes |= n, Ta |= n, u = 4;
                  break t;
                }
                n = bl, bl = u, n !== null && (bl === null ? bl = n : bl.push.apply(
                  bl,
                  n
                ));
              }
              u = i;
            }
            if (n = !1, u !== 2) continue;
          }
        }
        if (u === 1) {
          nu(t, 0), ke(t, l, 0, !0);
          break;
        }
        t: {
          switch (a = t, n = u, n) {
            case 0:
            case 1:
              throw Error(r(345));
            case 4:
              if ((l & 4194048) !== l && (l & 62914560) !== l)
                break;
            case 6:
              ke(
                a,
                l,
                Al,
                !Ve
              );
              break t;
            case 2:
              bl = null;
              break;
            case 3:
            case 5:
              break;
            default:
              throw Error(r(329));
          }
          if ((l & 62914560) === l && (u = Ei + 300 - pl(), 10 < u)) {
            if (ke(
              a,
              l,
              Al,
              !Ve
            ), xn(a, 0, !0) !== 0) break t;
            fe = l, a.timeoutHandle = ms(
              tm.bind(
                null,
                a,
                e,
                bl,
                zi,
                wf,
                l,
                Al,
                Ta,
                tu,
                Ve,
                n,
                "Throttled",
                -0,
                0
              ),
              u
            );
            break t;
          }
          tm(
            a,
            e,
            bl,
            zi,
            wf,
            l,
            Al,
            Ta,
            tu,
            Ve,
            n,
            null,
            -0,
            0
          );
        }
      }
      break;
    } while (!0);
    se(t);
  }
  function tm(t, l, e, a, u, n, i, c, f, y, S, z, v, b) {
    t.timeoutHandle = -1;
    var j = l.subtreeFlags, Z = (n & 335544064) === n;
    if (z = null, (Z || j & 8192 || (j & 16785408) === 16785408) && (z = {
      stylesheets: null,
      count: 0,
      imgCount: 0,
      imgBytes: 0,
      suspenseyImages: [],
      waitingForImages: !0,
      waitingForViewTransition: !1,
      unsuspend: Pl
    }, zl = null, Kd(
      l,
      n,
      z
    ), Z && (j = z, Z = t.containerInfo, Z = (Z.nodeType === 9 ? Z : Z.ownerDocument).__reactViewTransition, Z != null && (j.count++, j.waitingForViewTransition = !0, j = cn.bind(j), Z.finished.then(j, j))), j = (n & 62914560) === n ? Ei - pl() : (n & 4194048) === n ? Wd - pl() : 0, j = Ty(
      z,
      j
    ), j !== null)) {
      fe = n, t.cancelPendingCommit = j(
        fm.bind(
          null,
          t,
          l,
          n,
          e,
          a,
          u,
          i,
          c,
          f,
          y,
          S,
          z,
          null,
          v,
          b
        )
      ), ke(t, n, i, !y);
      return;
    }
    fm(
      t,
      l,
      n,
      e,
      a,
      u,
      i,
      c,
      f,
      y,
      S,
      z
    );
  }
  function bh(t) {
    for (var l = t; ; ) {
      var e = l.tag;
      if ((e === 0 || e === 11 || e === 15) && l.flags & 16384 && (e = l.updateQueue, e !== null && (e = e.stores, e !== null)))
        for (var a = 0; a < e.length; a++) {
          var u = e[a], n = u.getSnapshot;
          u = u.value;
          try {
            if (!El(n(), u)) return !1;
          } catch {
            return !1;
          }
        }
      if (e = l.child, l.subtreeFlags & 16384 && e !== null)
        e.return = l, l = e;
      else {
        if (l === t) break;
        for (; l.sibling === null; ) {
          if (l.return === null || l.return === t) return !0;
          l = l.return;
        }
        l.sibling.return = l.return, l = l.sibling;
      }
    }
    return !0;
  }
  function ke(t, l, e, a) {
    l = ks(t, l), l &= ~xi, l &= ~Ta, t.suspendedLanes |= l, t.pingedLanes &= ~l, a && (t.warmLanes |= l), a = t.expirationTimes;
    for (var u = l; 0 < u; ) {
      var n = 31 - Tl(u), i = 1 << n;
      a[n] = -1, u &= ~i;
    }
    e !== 0 && Ws(t, e, l);
  }
  function Ai() {
    return (yt & 6) === 0 ? (Pu(0), !1) : !0;
  }
  function Jf() {
    if (ft !== null) {
      if (xt === 0)
        var t = ft.return;
      else
        t = ft, be = oa = null, tf(t), Va = null, Bu = 0, t = ft;
      for (; t !== null; )
        xd(t.alternate, t), t = t.return;
      ft = null;
    }
  }
  function nu(t, l) {
    var e = t.timeoutHandle;
    return e !== -1 && (t.timeoutHandle = -1, Lh(e)), e = t.cancelPendingCommit, e !== null && (t.cancelPendingCommit = null, e()), fe = 0, Jf(), At = t, ft = e = ye(t.current, null), ot = l, xt = 0, Ol = null, Ve = !1, Pa = bu(t, l), Zf = !1, tu = Al = xi = Ta = Ke = Gt = 0, bl = Fu = null, wf = !1, Ee = ks(t, l), Bn(), e;
  }
  function lm(t, l) {
    nt = null, H.H = ci, l === wa || l === Jn ? (l = fr(), xt = 3) : l === Qc ? (l = fr(), xt = 4) : xt = l === yf ? 8 : l !== null && typeof l == "object" && typeof l.then == "function" ? 6 : 1, Ol = l, ft === null && (Gt = 1, fi(
      t,
      Hl(l, t.current)
    ));
  }
  function em() {
    var t = el.current;
    return t === null ? !0 : (ot & 4194048) === ot ? fl === null : (ot & 62914560) === ot || (ot & 536870912) !== 0 ? t === fl : !1;
  }
  function am() {
    var t = H.H;
    return H.H = ci, t === null ? ci : t;
  }
  function um() {
    var t = H.A;
    return H.A = yh, t;
  }
  function Mi() {
    Gt = 4, Ve || (ot & 4194048) !== ot && el.current !== null || (Pa = !0), (Ke & 134217727) === 0 && (Ta & 134217727) === 0 || At === null || ke(
      At,
      ot,
      Al,
      !1
    );
  }
  function kf(t, l, e) {
    var a = yt;
    yt |= 2;
    var u = am(), n = um();
    (At !== t || ot !== l) && (zi = null, nu(t, l)), l = !1;
    var i = Gt;
    t: do
      try {
        if (xt !== 0 && ft !== null) {
          var c = ft, f = Ol;
          switch (xt) {
            case 8:
              Jf(), i = 6;
              break t;
            case 3:
            case 2:
            case 9:
            case 6:
              el.current === null && (l = !0);
              var y = xt;
              if (xt = 0, Ol = null, iu(t, c, f, y), e && Pa) {
                i = 0;
                break t;
              }
              break;
            default:
              y = xt, xt = 0, Ol = null, iu(t, c, f, y);
          }
        }
        Sh(), i = Gt;
        break;
      } catch (S) {
        lm(t, S);
      }
    while (!0);
    return l && t.shellSuspendCounter++, be = oa = null, yt = a, H.H = u, H.A = n, ft === null && (At = null, ot = 0, Bn()), i;
  }
  function Sh() {
    for (; ft !== null; ) nm(ft);
  }
  function ph(t, l) {
    var e = yt;
    yt |= 2;
    var a = am(), u = um();
    At !== t || ot !== l ? (zi = null, Ni = pl() + 500, nu(t, l)) : Pa = bu(
      t,
      l
    );
    t: do
      try {
        if (xt !== 0 && ft !== null) {
          l = ft;
          var n = Ol;
          l: switch (xt) {
            case 1:
              xt = 0, Ol = null, iu(t, l, n, 1);
              break;
            case 2:
            case 9:
              if (ir(n)) {
                xt = 0, Ol = null, im(l);
                break;
              }
              l = function() {
                xt !== 2 && xt !== 9 || At !== t || (xt = 7), se(t);
              }, n.then(l, l);
              break t;
            case 3:
              xt = 7;
              break t;
            case 4:
              xt = 5;
              break t;
            case 7:
              ir(n) ? (xt = 0, Ol = null, im(l)) : (xt = 0, Ol = null, iu(t, l, n, 7));
              break;
            case 5:
              var i = null;
              switch (ft.tag) {
                case 26:
                  i = ft.memoizedState;
                case 5:
                case 27:
                  var c = ft;
                  if (i ? Fm(i) : c.stateNode.complete) {
                    xt = 0, Ol = null;
                    var f = c.sibling;
                    if (f !== null) ft = f;
                    else {
                      var y = c.return;
                      y !== null ? (ft = y, Ci(y)) : ft = null;
                    }
                    break l;
                  }
              }
              xt = 0, Ol = null, iu(t, l, n, 5);
              break;
            case 6:
              xt = 0, Ol = null, iu(t, l, n, 6);
              break;
            case 8:
              Jf(), Gt = 6;
              break t;
            default:
              throw Error(r(462));
          }
        }
        _h();
        break;
      } catch (S) {
        lm(t, S);
      }
    while (!0);
    return be = oa = null, H.H = a, H.A = u, yt = e, ft !== null ? 0 : (At = null, ot = 0, Bn(), Gt);
  }
  function _h() {
    for (; ft !== null && !Y0(); )
      nm(ft);
  }
  function nm(t) {
    var l = _d(t.alternate, t, Ee);
    t.memoizedProps = t.pendingProps, l === null ? Ci(t) : ft = l;
  }
  function im(t) {
    var l = t, e = l.alternate;
    switch (l.tag) {
      case 15:
      case 0:
        l = vd(
          e,
          l,
          l.pendingProps,
          l.type,
          void 0,
          ot
        );
        break;
      case 11:
        l = vd(
          e,
          l,
          l.pendingProps,
          l.type.render,
          l.ref,
          ot
        );
        break;
      case 5:
        tf(l);
        var a = l;
        a === Wt && (ct ? (Ln(a), a.tag === 5 && a.stateNode != null && (Rt = a.stateNode)) : (Ln(a), ct = !0));
      default:
        xd(e, l), l = ft = $o(l, Ee), l = _d(e, l, Ee);
    }
    t.memoizedProps = t.pendingProps, l === null ? Ci(t) : ft = l;
  }
  function iu(t, l, e, a) {
    be = oa = null, tf(l), Va = null, Bu = 0;
    var u = l.return;
    try {
      if (fh(
        t,
        u,
        l,
        e,
        ot
      )) {
        Gt = 1, fi(
          t,
          Hl(e, t.current)
        ), ft = null;
        return;
      }
    } catch (n) {
      if (u !== null) throw ft = u, n;
      Gt = 1, fi(
        t,
        Hl(e, t.current)
      ), ft = null;
      return;
    }
    l.flags & 32768 ? (ct || a === 1 ? t = !0 : Pa || (ot & 536870912) !== 0 ? t = !1 : (Ve = t = !0, (a === 2 || a === 9 || a === 3 || a === 6) && (a = el.current, a !== null && a.tag === 13 && (a.flags |= 16384))), cm(l, t)) : Ci(l);
  }
  function Ci(t) {
    var l = t;
    do {
      if ((l.flags & 32768) !== 0) {
        cm(
          l,
          Ve
        );
        return;
      }
      t = l.return;
      var e = dh(
        l.alternate,
        l,
        Ee
      );
      if (e !== null) {
        ft = e;
        return;
      }
      if (l = l.sibling, l !== null) {
        ft = l;
        return;
      }
      ft = l = t;
    } while (l !== null);
    Gt === 0 && (Gt = 5);
  }
  function cm(t, l) {
    do {
      var e = mh(t.alternate, t);
      if (e !== null) {
        e.flags &= 32767, ft = e;
        return;
      }
      if (e = t.return, e !== null && (e.flags |= 32768, e.subtreeFlags = 0, e.deletions = null), !l && (t = t.sibling, t !== null)) {
        ft = t;
        return;
      }
      ft = t = e;
    } while (t !== null);
    Gt = 6, ft = null;
  }
  function fm(t, l, e, a, u, n, i, c, f, y, S, z) {
    t.cancelPendingCommit = null;
    do
      Ri();
    while (Bt !== 0);
    if ((yt & 6) !== 0) throw Error(r(327));
    if (l !== null) {
      if (l === t.current) throw Error(r(177));
      t === At && (ft = At = null, ot = 0), xa = l, $l = t, fe = e, Kf = u, Fd = a, Th(
        t,
        l,
        e,
        i,
        c,
        f,
        z
      );
    }
  }
  function Th(t, l, e, a, u, n, i) {
    var c = l.lanes | l.childLanes;
    if (Vf = c, c |= Ac, k0(
      t,
      e,
      c,
      a,
      u,
      n
    ), eu = null, (e & 335544064) === e ? (au = Wv(t), a = 10262) : (au = null, a = 10256), (l.subtreeFlags & a) !== 0 || (l.flags & a) !== 0 ? (t.callbackNode = null, t.callbackPriority = 0, Ah(Sn, function() {
      return If(), null;
    })) : (t.callbackNode = null, t.callbackPriority = 0), yi = !1, a = (l.flags & 13878) !== 0, (l.subtreeFlags & 13878) !== 0 || a) {
      a = H.T, H.T = null, u = V.p, V.p = 2, n = yt, yt |= 4;
      try {
        vh(t, l, e);
      } finally {
        yt = n, V.p = u, H.T = a;
      }
    }
    Bt = 1, yi ? lu = kh(
      i,
      t.containerInfo,
      au,
      $f,
      Wf,
      Eh,
      Ff,
      If,
      xh
    ) : ($f(), Wf(), Ff());
  }
  function xh(t) {
    if (Bt !== 0) {
      var l = $l.onRecoverableError;
      l(t, { componentStack: null });
    }
  }
  function Eh() {
    Bt === 3 && (Bt = 0, wd(xa, $l), Bt = 4);
  }
  function $f() {
    if (Bt === 1) {
      Bt = 0;
      var t = $l, l = xa, e = fe, a = (l.flags & 13878) !== 0;
      if ((l.subtreeFlags & 13878) !== 0 || a) {
        a = H.T, H.T = null;
        var u = V.p;
        V.p = 2;
        var n = yt;
        yt |= 4;
        try {
          ku = Si = !1, Ld(l, t, e), e = os;
          var i = Xo(t.containerInfo), c = e.focusedElem, f = e.selectionRange;
          if (i !== c && c && c.ownerDocument && Yo(
            c.ownerDocument.documentElement,
            c
          )) {
            if (f !== null && xc(c)) {
              var y = f.start, S = f.end;
              if (S === void 0 && (S = y), "selectionStart" in c)
                c.selectionStart = y, c.selectionEnd = Math.min(
                  S,
                  c.value.length
                );
              else {
                var z = c.ownerDocument || document, v = z && z.defaultView || window;
                if (v.getSelection) {
                  var b = v.getSelection(), j = c.textContent.length, Z = Math.min(f.start, j), it = f.end === void 0 ? Z : Math.min(f.end, j);
                  !b.extend && Z > it && (i = it, it = Z, Z = i);
                  var h = qo(
                    c,
                    Z
                  ), d = qo(
                    c,
                    it
                  );
                  if (h && d && (b.rangeCount !== 1 || b.anchorNode !== h.node || b.anchorOffset !== h.offset || b.focusNode !== d.node || b.focusOffset !== d.offset)) {
                    var g = z.createRange();
                    g.setStart(h.node, h.offset), b.removeAllRanges(), Z > it ? (b.addRange(g), b.extend(d.node, d.offset)) : (g.setEnd(d.node, d.offset), b.addRange(g));
                  }
                }
              }
            }
            for (z = [], b = c; b = b.parentNode; )
              b.nodeType === 1 && z.push({
                element: b,
                left: b.scrollLeft,
                top: b.scrollTop
              });
            for (typeof c.focus == "function" && c.focus(), c = 0; c < z.length; c++) {
              var N = z[c];
              N.element.scrollLeft = N.left, N.element.scrollTop = N.top;
            }
          }
          vu = !!ss, os = ss = null;
        } finally {
          yt = n, V.p = u, H.T = a;
        }
      }
      t.current = l, Bt = 2;
    }
  }
  function Wf() {
    if (Bt === 2) {
      Bt = 0;
      var t = $l, l = xa, e = (l.flags & 8772) !== 0;
      if ((l.subtreeFlags & 8772) !== 0 || e) {
        e = H.T, H.T = null;
        var a = V.p;
        V.p = 2;
        var u = yt;
        yt |= 4;
        try {
          Bd(t, l.alternate, l);
        } finally {
          yt = u, V.p = a, H.T = e;
        }
      }
      Bt = 3;
    }
  }
  function Ff() {
    if (Bt === 4 || Bt === 3) {
      Bt = 0;
      var t = lu;
      lu = null, X0();
      var l = $l, e = xa, a = fe, u = Fd, n = (a & 335544064) === a ? 10262 : 10256;
      if ((e.subtreeFlags & n) !== 0 || (e.flags & n) !== 0 ? Bt = 5 : (Bt = 0, xa = $l = null, sm(l, l.pendingLanes)), n = l.pendingLanes, n === 0 && (Je = null), nc(a), e = e.stateNode, _l && typeof _l.onCommitFiberRoot == "function")
        try {
          _l.onCommitFiberRoot(
            gu,
            e,
            void 0,
            (e.current.flags & 128) === 128
          );
        } catch {
        }
      if (u !== null) {
        e = H.T, n = V.p, V.p = 2, H.T = null;
        try {
          for (var i = l.onRecoverableError, c = 0; c < u.length; c++) {
            var f = u[c];
            i(f.value, {
              componentStack: f.stack
            });
          }
        } finally {
          H.T = e, V.p = n;
        }
      }
      if (u = eu, i = au, au = null, u !== null && (eu = null, i === null && (i = []), t !== null))
        for (f = 0; f < u.length; f++)
          e = (0, u[f])(
            i
          ), e !== void 0 && t.finished.finally(e);
      (fe & 3) !== 0 && Ri(), se(l), n = l.pendingLanes, (a & 261930) !== 0 && (n & 42) !== 0 ? l === Oi ? Iu++ : (Iu = 0, Oi = l) : (Iu = 0, Oi = null), Pu(0);
    }
  }
  function sm(t, l) {
    (t.pooledCacheLanes &= l) === 0 && (l = t.pooledCache, l != null && (t.pooledCache = null, Uu(l)));
  }
  function Ri() {
    return lu !== null && (lu.skipTransition(), lu = null), $f(), Wf(), Ff(), If();
  }
  function If() {
    if (Bt !== 5) return !1;
    var t = $l, l = Vf;
    Vf = 0;
    var e = nc(fe), a = H.T, u = V.p;
    try {
      V.p = 32 > e ? 32 : e, H.T = null, e = Kf, Kf = null;
      var n = $l, i = fe;
      if (Bt = 0, xa = $l = null, fe = 0, (yt & 6) !== 0) throw Error(r(331));
      var c = yt;
      if (yt |= 4, kd(n.current), Vd(
        n,
        n.current,
        i,
        e
      ), yt = c, Pu(0, !1), _l && typeof _l.onPostCommitFiberRoot == "function")
        try {
          _l.onPostCommitFiberRoot(gu, n);
        } catch {
        }
      return !0;
    } finally {
      V.p = u, H.T = a, sm(t, l);
    }
  }
  function om(t, l, e) {
    l = Hl(e, l), l = hf(t.stateNode, l, 2), t = Xe(t, l, 2), t !== null && (Su(t, 2), se(t));
  }
  function Et(t, l, e) {
    if (t.tag === 3)
      om(t, t, e);
    else
      for (; l !== null; ) {
        if (l.tag === 3) {
          om(
            l,
            t,
            e
          );
          break;
        } else if (l.tag === 1) {
          var a = l.stateNode;
          if (typeof l.type.getDerivedStateFromError == "function" || typeof a.componentDidCatch == "function" && (Je === null || !Je.has(a))) {
            t = Hl(e, t), e = id(2), a = Xe(l, e, 2), a !== null && (cd(
              e,
              a,
              l,
              t
            ), Su(a, 2), se(a));
            break;
          }
        }
        l = l.return;
      }
  }
  function Pf(t, l, e) {
    var a = t.pingCache;
    if (a === null) {
      a = t.pingCache = new gh();
      var u = /* @__PURE__ */ new Set();
      a.set(l, u);
    } else
      u = a.get(l), u === void 0 && (u = /* @__PURE__ */ new Set(), a.set(l, u));
    u.has(e) || (Zf = !0, u.add(e), t = Nh.bind(null, t, l, e), l.then(t, t));
  }
  function Nh(t, l, e) {
    var a = t.pingCache;
    a !== null && a.delete(l), t.pingedLanes |= t.suspendedLanes & e, t.warmLanes &= ~e, At === t && (ot & e) === e && ((Gt === 4 || Gt === 3 && (ot & 62914560) === ot && 300 > pl() - Ei) && (yt & 2) === 0 ? nu(t, 0) : xi |= e, tu === ot && (tu = 0)), se(t);
  }
  function rm(t, l) {
    l === 0 && (l = $s()), t = ca(t, l), t !== null && (Su(t, l), se(t));
  }
  function zh(t) {
    var l = t.memoizedState, e = 0;
    l !== null && (e = l.retryLane), rm(t, e);
  }
  function Oh(t, l) {
    var e = 0;
    switch (t.tag) {
      case 31:
      case 13:
        var a = t.stateNode, u = t.memoizedState;
        u !== null && (e = u.retryLane);
        break;
      case 19:
        a = t.stateNode;
        break;
      case 22:
        a = t.stateNode._retryCache;
        break;
      default:
        throw Error(r(314));
    }
    a !== null && a.delete(l), rm(t, e);
  }
  function Ah(t, l) {
    return lc(t, l);
  }
  var cu = null, fu = null, ts = !1, Di = !1, ls = !1, $e = 0;
  function se(t) {
    t !== fu && t.next === null && (fu === null ? cu = fu = t : fu = fu.next = t), Di = !0, ts || (ts = !0, Ch());
  }
  function Pu(t, l) {
    if (!ls && Di) {
      ls = !0;
      do
        for (var e = !1, a = cu; a !== null; ) {
          if (t !== 0) {
            var u = a.pendingLanes;
            if (u === 0) var n = 0;
            else {
              var i = a.suspendedLanes, c = a.pingedLanes;
              n = (1 << 31 - Tl(42 | t) + 1) - 1, n &= u & ~(i & ~c), n = n & 201326741 ? n & 201326741 | 1 : n ? n | 2 : 0;
            }
            n !== 0 && (e = !0, hm(a, n));
          } else
            n = ot, n = xn(
              a,
              a === At ? n : 0,
              a.cancelPendingCommit !== null || a.timeoutHandle !== -1
            ), (n & 3) === 0 || bu(a, n) || (e = !0, hm(a, n));
          a = a.next;
        }
      while (e);
      ls = !1;
    }
  }
  function Mh() {
    dm();
  }
  function dm() {
    Di = ts = !1;
    var t = 0;
    $e !== 0 && Qh() && (t = $e);
    for (var l = pl(), e = null, a = cu; a !== null; ) {
      var u = a.next, n = mm(a, l);
      n === 0 ? (a.next = null, e === null ? cu = u : e.next = u, u === null && (fu = e)) : (e = a, (t !== 0 || (n & 3) !== 0) && (Di = !0)), a = u;
    }
    Bt !== 0 && Bt !== 5 || Pu(t), $e !== 0 && ($e = 0);
  }
  function mm(t, l) {
    for (var e = t.suspendedLanes, a = t.pingedLanes, u = t.expirationTimes, n = t.pendingLanes & -62914561; 0 < n; ) {
      var i = 31 - Tl(n), c = 1 << i, f = u[i];
      f === -1 ? ((c & e) === 0 || (c & a) !== 0) && (u[i] = J0(c, l)) : f <= l && (t.expiredLanes |= c), n &= ~c;
    }
    if (l = At, e = ot, e = xn(
      t,
      t === l ? e : 0,
      t.cancelPendingCommit !== null || t.timeoutHandle !== -1
    ), a = t.callbackNode, e === 0 || t === l && (xt === 2 || xt === 9) || t.cancelPendingCommit !== null)
      return a !== null && a !== null && ec(a), t.callbackNode = null, t.callbackPriority = 0;
    if ((e & 3) === 0 || bu(t, e)) {
      if (l = e & -e, l === t.callbackPriority) return l;
      switch (a !== null && ec(a), nc(e)) {
        case 2:
        case 8:
          e = Ks;
          break;
        case 32:
          e = Sn;
          break;
        case 268435456:
          e = Js;
          break;
        default:
          e = Sn;
      }
      return a = vm.bind(null, t), e = lc(e, a), t.callbackPriority = l, t.callbackNode = e, l;
    }
    return a !== null && a !== null && ec(a), t.callbackPriority = 2, t.callbackNode = null, 2;
  }
  function vm(t, l) {
    if (Bt !== 0 && Bt !== 5)
      return t.callbackNode = null, t.callbackPriority = 0, null;
    var e = t.callbackNode;
    if (Ri() && t.callbackNode !== e)
      return null;
    var a = ot;
    return a = xn(
      t,
      t === At ? a : 0,
      t.cancelPendingCommit !== null || t.timeoutHandle !== -1
    ), a === 0 ? null : (Pd(t, a, l), mm(t, pl()), t.callbackNode != null && t.callbackNode === e ? vm.bind(null, t) : null);
  }
  function hm(t, l) {
    if (Ri()) return null;
    Pd(t, l, !0);
  }
  function Ch() {
    Zh(function() {
      (yt & 6) !== 0 ? lc(
        Vs,
        Mh
      ) : dm();
    });
  }
  function es() {
    if ($e === 0) {
      var t = ma;
      t === 0 && (t = pn, pn <<= 1, (pn & 261888) === 0 && (pn = 256)), $e = t;
    }
    return $e;
  }
  function ym(t) {
    return t == null || typeof t == "symbol" || typeof t == "boolean" ? null : typeof t == "function" ? t : An(t);
  }
  function Rh(t, l, e, a, u) {
    if (l === "submit" && e && e.stateNode === u) {
      var n = ym(
        (u[vl] || null).action
      ), i = a.submitter;
      i && (l = (l = i[vl] || null) ? ym(l.formAction) : i.getAttribute("formAction"), l !== null && (n = l, i = null));
      var c = new Dn(
        "action",
        "action",
        null,
        a,
        u
      );
      t.push({
        event: c,
        listeners: [
          {
            instance: null,
            listener: function() {
              if (a.defaultPrevented) {
                if ($e !== 0) {
                  var f = new FormData(u, i);
                  of(
                    e,
                    {
                      pending: !0,
                      data: f,
                      method: u.method,
                      action: n
                    },
                    null,
                    f
                  );
                }
              } else
                typeof n == "function" && (c.preventDefault(), f = new FormData(u, i), of(
                  e,
                  {
                    pending: !0,
                    data: f,
                    method: u.method,
                    action: n
                  },
                  n,
                  f
                ));
            },
            currentTarget: u
          }
        ]
      });
    }
  }
  for (var as = 0; as < Oc.length; as++) {
    var us = Oc[as], Dh = us.toLowerCase(), Uh = us[0].toUpperCase() + us.slice(1);
    Vl(
      Dh,
      "on" + Uh
    );
  }
  Vl(Lo, "onAnimationEnd"), Vl(Zo, "onAnimationIteration"), Vl(wo, "onAnimationStart"), Vl("dblclick", "onDoubleClick"), Vl("focusin", "onFocus"), Vl("focusout", "onBlur"), Vl(Lv, "onTransitionRun"), Vl(Zv, "onTransitionStart"), Vl(wv, "onTransitionCancel"), Vl(Vo, "onTransitionEnd"), Ca("onMouseEnter", ["mouseout", "mouseover"]), Ca("onMouseLeave", ["mouseout", "mouseover"]), Ca("onPointerEnter", ["pointerout", "pointerover"]), Ca("onPointerLeave", ["pointerout", "pointerover"]), ua(
    "onChange",
    "change click focusin focusout input keydown keyup selectionchange".split(" ")
  ), ua(
    "onSelect",
    "focusout contextmenu dragend focusin keydown keyup mousedown mouseup selectionchange".split(
      " "
    )
  ), ua("onBeforeInput", [
    "compositionend",
    "keypress",
    "textInput",
    "paste"
  ]), ua(
    "onCompositionEnd",
    "compositionend focusout keydown keypress keyup mousedown".split(" ")
  ), ua(
    "onCompositionStart",
    "compositionstart focusout keydown keypress keyup mousedown".split(" ")
  ), ua(
    "onCompositionUpdate",
    "compositionupdate focusout keydown keypress keyup mousedown".split(" ")
  );
  var tn = "abort canplay canplaythrough durationchange emptied encrypted ended error loadeddata loadedmetadata loadstart pause play playing progress ratechange resize seeked seeking stalled suspend timeupdate volumechange waiting".split(
    " "
  ), jh = new Set(
    "beforetoggle cancel close invalid load scroll scrollend toggle".split(" ").concat(tn)
  );
  function gm(t, l) {
    l = (l & 4) !== 0;
    for (var e = 0; e < t.length; e++) {
      var a = t[e], u = a.event;
      a = a.listeners;
      t: {
        var n = void 0;
        if (l)
          for (var i = a.length - 1; 0 <= i; i--) {
            var c = a[i], f = c.instance, y = c.currentTarget;
            if (c = c.listener, f !== n && u.isPropagationStopped())
              break t;
            n = c, u.currentTarget = y;
            try {
              n(u);
            } catch (S) {
              Hn(S);
            }
            u.currentTarget = null, n = f;
          }
        else
          for (i = 0; i < a.length; i++) {
            if (c = a[i], f = c.instance, y = c.currentTarget, c = c.listener, f !== n && u.isPropagationStopped())
              break t;
            n = c, u.currentTarget = y;
            try {
              n(u);
            } catch (S) {
              Hn(S);
            }
            u.currentTarget = null, n = f;
          }
      }
    }
  }
  function st(t, l) {
    var e = l[lo];
    e === void 0 && (e = l[lo] = /* @__PURE__ */ new Set());
    var a = t + "__bubble";
    e.has(a) || (bm(l, t, 2, !1), e.add(a));
  }
  function ns(t, l, e) {
    var a = 0;
    l && (a |= 4), bm(
      e,
      t,
      a,
      l
    );
  }
  var Ui = "_reactListening" + Math.random().toString(36).slice(2);
  function is(t) {
    if (!t[Ui]) {
      t[Ui] = !0, uo.forEach(function(e) {
        e !== "selectionchange" && (jh.has(e) || ns(e, !1, t), ns(e, !0, t));
      });
      var l = t.nodeType === 9 ? t : t.ownerDocument;
      l === null || l[Ui] || (l[Ui] = !0, ns("selectionchange", !1, l));
    }
  }
  function bm(t, l, e, a) {
    switch (c0(l)) {
      case 2:
        var u = zy;
        break;
      case 8:
        u = Oy;
        break;
      default:
        u = zs;
    }
    e = u.bind(
      null,
      l,
      e,
      t
    ), u = void 0, !mc || l !== "touchstart" && l !== "touchmove" && l !== "wheel" || (u = !0), a ? u !== void 0 ? t.addEventListener(l, e, {
      capture: !0,
      passive: u
    }) : t.addEventListener(l, e, !0) : u !== void 0 ? t.addEventListener(l, e, {
      passive: u
    }) : t.addEventListener(l, e, !1);
  }
  function cs(t, l, e, a, u) {
    var n = a;
    if ((l & 1) === 0 && (l & 2) === 0 && a !== null)
      t: for (; ; ) {
        if (a === null) return;
        var i = a.tag;
        if (i === 3 || i === 4) {
          var c = a.stateNode.containerInfo;
          if (c === u) break;
          if (i === 4)
            for (i = a.return; i !== null; ) {
              var f = i.tag;
              if ((f === 3 || f === 4) && i.stateNode.containerInfo === u)
                return;
              i = i.return;
            }
          for (; c !== null; ) {
            if (i = aa(c), i === null) return;
            if (f = i.tag, f === 5 || f === 6 || f === 26 || f === 27) {
              a = n = i;
              continue t;
            }
            c = c.parentNode;
          }
        }
        a = a.return;
      }
    bo(function() {
      var y = n, S = rc(e), z = [];
      t: {
        var v = Ko.get(t);
        if (v !== void 0) {
          var b = Dn, j = t;
          switch (t) {
            case "keypress":
              if (Cn(e) === 0) break t;
            case "keydown":
            case "keyup":
              b = bv;
              break;
            case "focusin":
              j = "focus", b = gc;
              break;
            case "focusout":
              j = "blur", b = gc;
              break;
            case "beforeblur":
            case "afterblur":
              b = gc;
              break;
            case "click":
              if (e.button === 2) break t;
            case "auxclick":
            case "dblclick":
            case "mousedown":
            case "mousemove":
            case "mouseup":
            case "mouseout":
            case "mouseover":
            case "contextmenu":
              b = _o;
              break;
            case "drag":
            case "dragend":
            case "dragenter":
            case "dragexit":
            case "dragleave":
            case "dragover":
            case "dragstart":
            case "drop":
              b = iv;
              break;
            case "touchcancel":
            case "touchend":
            case "touchmove":
            case "touchstart":
              b = xv;
              break;
            case Lo:
            case Zo:
            case wo:
              b = sv;
              break;
            case Vo:
              b = Nv;
              break;
            case "scroll":
            case "scrollend":
              b = uv;
              break;
            case "wheel":
              b = Ov;
              break;
            case "copy":
            case "cut":
            case "paste":
              b = rv;
              break;
            case "gotpointercapture":
            case "lostpointercapture":
            case "pointercancel":
            case "pointerdown":
            case "pointermove":
            case "pointerout":
            case "pointerover":
            case "pointerup":
              b = xo;
              break;
            case "submit":
              b = _v;
              break;
            case "toggle":
            case "beforetoggle":
              b = Mv;
          }
          var Z = (l & 4) !== 0, it = !Z && (t === "scroll" || t === "scrollend"), h = Z ? v !== null ? v + "Capture" : null : v;
          Z = [];
          for (var d = y, g; d !== null; ) {
            var N = d;
            if (g = N.stateNode, N = N.tag, N !== 5 && N !== 26 && N !== 27 || g === null || h === null || (N = Tu(d, h), N != null && Z.push(
              ln(d, N, g)
            )), it) break;
            d = d.return;
          }
          0 < Z.length && (v = new b(
            v,
            j,
            null,
            e,
            S
          ), z.push({ event: v, listeners: Z }));
        }
      }
      if ((l & 7) === 0) {
        t: {
          if (b = t === "mouseover" || t === "pointerover", v = t === "mouseout" || t === "pointerout", b && e !== oc && (j = e.relatedTarget || e.fromElement) && (aa(j) || j[Oa]))
            break t;
          (v || b) && (j = S.window === S ? S : (b = S.ownerDocument) ? b.defaultView || b.parentWindow : window, v ? (b = e.relatedTarget || e.toElement, v = y, b = b ? aa(b) : null, b !== null && (it = J(b), Z = b.tag, b !== it || Z !== 5 && Z !== 27 && Z !== 6) && (b = null)) : (v = null, b = y), v !== b && (Z = _o, N = "onMouseLeave", h = "onMouseEnter", d = "mouse", (t === "pointerout" || t === "pointerover") && (Z = xo, N = "onPointerLeave", h = "onPointerEnter", d = "pointer"), it = v == null ? j : _u(v), g = b == null ? j : _u(b), j = new Z(
            N,
            d + "leave",
            v,
            e,
            S
          ), j.target = it, j.relatedTarget = g, N = null, aa(S) === y && (Z = new Z(
            h,
            d + "enter",
            b,
            e,
            S
          ), Z.target = g, Z.relatedTarget = it, N = Z), it = N, Z = v && b ? pt(
            v,
            b,
            Hh
          ) : null, v !== null && Sm(
            z,
            j,
            v,
            Z,
            !1
          ), b !== null && it !== null && Sm(
            z,
            it,
            b,
            Z,
            !0
          )));
        }
        t: {
          if (v = y ? _u(y) : window, b = v.nodeName && v.nodeName.toLowerCase(), b === "select" || b === "input" && v.type === "file")
            var Q = Ro;
          else if (Mo(v))
            if (Do)
              Q = Xv;
            else {
              Q = qv;
              var rt = Bv;
            }
          else
            b = v.nodeName, !b || b.toLowerCase() !== "input" || v.type !== "checkbox" && v.type !== "radio" ? y && sc(y.elementType) && (Q = Ro) : Q = Yv;
          if (Q && (Q = Q(t, y))) {
            Co(
              z,
              Q,
              e,
              S
            );
            break t;
          }
          rt && rt(t, v, y);
        }
        switch (rt = y ? _u(y) : window, t) {
          case "focusin":
            (Mo(rt) || rt.contentEditable === "true") && (Ba = rt, Ec = y, Cu = null);
            break;
          case "focusout":
            Cu = Ec = Ba = null;
            break;
          case "mousedown":
            Nc = !0;
            break;
          case "contextmenu":
          case "mouseup":
          case "dragend":
            Nc = !1, Go(z, e, S);
            break;
          case "selectionchange":
            if (Qv) break;
          case "keydown":
          case "keyup":
            Go(z, e, S);
        }
        var K;
        if (Sc)
          t: {
            switch (t) {
              case "compositionstart":
                var P = "onCompositionStart";
                break t;
              case "compositionend":
                P = "onCompositionEnd";
                break t;
              case "compositionupdate":
                P = "onCompositionUpdate";
                break t;
            }
            P = void 0;
          }
        else
          Ha ? Oo(t, e) && (P = "onCompositionEnd") : t === "keydown" && e.keyCode === 229 && (P = "onCompositionStart");
        P && (Eo && e.locale !== "ko" && (Ha || P !== "onCompositionStart" ? P === "onCompositionEnd" && Ha && (K = So()) : (Ce = S, vc = "value" in Ce ? Ce.value : Ce.textContent, Ha = !0)), rt = ji(y, P), 0 < rt.length && (P = new To(
          P,
          t,
          null,
          e,
          S
        ), z.push({ event: P, listeners: rt }), K ? P.data = K : (K = Ao(e), K !== null && (P.data = K)))), (K = Rv ? Dv(t, e) : Uv(t, e)) && (P = ji(y, "onBeforeInput"), 0 < P.length && (rt = new To(
          "onBeforeInput",
          "beforeinput",
          null,
          e,
          S
        ), z.push({
          event: rt,
          listeners: P
        }), rt.data = K)), Rh(
          z,
          t,
          y,
          e,
          S
        );
      }
      gm(z, l);
    });
  }
  function ln(t, l, e) {
    return {
      instance: t,
      listener: l,
      currentTarget: e
    };
  }
  function ji(t, l) {
    for (var e = l + "Capture", a = []; t !== null; ) {
      var u = t, n = u.stateNode;
      if (u = u.tag, u !== 5 && u !== 26 && u !== 27 || n === null || (u = Tu(t, e), u != null && a.unshift(
        ln(t, u, n)
      ), u = Tu(t, l), u != null && a.push(
        ln(t, u, n)
      )), t.tag === 3) return a;
      t = t.return;
    }
    return [];
  }
  function Hh(t) {
    if (t === null) return null;
    do
      t = t.return;
    while (t && t.tag !== 5 && t.tag !== 27);
    return t || null;
  }
  function Sm(t, l, e, a, u) {
    for (var n = l._reactName, i = []; e !== null && e !== a; ) {
      var c = e, f = c.alternate, y = c.stateNode;
      if (c = c.tag, f !== null && f === a) break;
      c !== 5 && c !== 26 && c !== 27 || y === null || (f = y, u ? (y = Tu(e, n), y != null && i.unshift(
        ln(e, y, f)
      )) : u || (y = Tu(e, n), y != null && i.push(
        ln(e, y, f)
      ))), e = e.return;
    }
    i.length !== 0 && t.push({ event: l, listeners: i });
  }
  var Bh = /\r\n?/g, qh = /\u0000|\uFFFD/g;
  function pm(t) {
    return (typeof t == "string" ? t : "" + t).replace(Bh, `
`).replace(qh, "");
  }
  function _m(t, l) {
    return l = pm(l), pm(t) === l;
  }
  function Nt(t, l, e, a, u, n) {
    switch (e) {
      case "children":
        if (typeof a == "string")
          l === "body" || l === "textarea" && a === "" || Da(t, a);
        else if (typeof a == "number" || typeof a == "bigint")
          l !== "body" && Da(t, "" + a);
        else return;
        break;
      case "className":
        On(t, "class", a);
        break;
      case "tabIndex":
        On(t, "tabindex", a);
        break;
      case "dir":
      case "role":
      case "viewBox":
      case "width":
      case "height":
        On(t, e, a);
        break;
      case "style":
        yo(t, a, n);
        return;
      case "data":
        if (l !== "object") {
          On(t, "data", a);
          break;
        }
      case "src":
      case "href":
        if (a === "" && (l !== "a" || e !== "href")) {
          t.removeAttribute(e);
          break;
        }
        if (a == null || typeof a == "function" || typeof a == "symbol" || typeof a == "boolean") {
          t.removeAttribute(e);
          break;
        }
        a = An(a), t.setAttribute(e, a);
        break;
      case "action":
      case "formAction":
        if (typeof a == "function") {
          t.setAttribute(
            e,
            "javascript:throw new Error('A React form was unexpectedly submitted. If you called form.submit() manually, consider using form.requestSubmit() instead. If you\\'re trying to use event.stopPropagation() in a submit event handler, consider also calling event.preventDefault().')"
          );
          break;
        } else
          typeof n == "function" && (e === "formAction" ? (l !== "input" && Nt(t, l, "name", u.name, u, null), Nt(
            t,
            l,
            "formEncType",
            u.formEncType,
            u,
            null
          ), Nt(
            t,
            l,
            "formMethod",
            u.formMethod,
            u,
            null
          ), Nt(
            t,
            l,
            "formTarget",
            u.formTarget,
            u,
            null
          )) : (Nt(t, l, "encType", u.encType, u, null), Nt(t, l, "method", u.method, u, null), Nt(t, l, "target", u.target, u, null)));
        if (a == null || typeof a == "symbol" || typeof a == "boolean") {
          t.removeAttribute(e);
          break;
        }
        a = An(a), t.setAttribute(e, a);
        break;
      case "onClick":
        a != null && (t.onclick = Pl);
        return;
      case "onScroll":
        a != null && st("scroll", t);
        return;
      case "onScrollEnd":
        a != null && st("scrollend", t);
        return;
      case "dangerouslySetInnerHTML":
        if (a != null) {
          if (typeof a != "object" || !("__html" in a))
            throw Error(r(61));
          if (e = a.__html, e != null) {
            if (u.children != null) throw Error(r(60));
            n?.__html !== e && (t.innerHTML = e);
          }
        }
        break;
      case "multiple":
        t.multiple = a && typeof a != "function" && typeof a != "symbol";
        break;
      case "muted":
        t.muted = a && typeof a != "function" && typeof a != "symbol";
        break;
      case "suppressContentEditableWarning":
      case "suppressHydrationWarning":
      case "defaultValue":
      case "defaultChecked":
      case "innerHTML":
      case "ref":
        break;
      case "autoFocus":
        break;
      case "xlinkHref":
        if (a == null || typeof a == "function" || typeof a == "boolean" || typeof a == "symbol") {
          t.removeAttribute("xlink:href");
          break;
        }
        e = An(a), t.setAttributeNS(
          "http://www.w3.org/1999/xlink",
          "xlink:href",
          e
        );
        break;
      case "contentEditable":
      case "spellCheck":
      case "draggable":
      case "value":
      case "autoReverse":
      case "externalResourcesRequired":
      case "focusable":
      case "preserveAlpha":
        a != null && typeof a != "function" && typeof a != "symbol" ? t.setAttribute(e, a) : t.removeAttribute(e);
        break;
      case "inert":
      case "allowFullScreen":
      case "async":
      case "autoPlay":
      case "controls":
      case "credentialless":
      case "default":
      case "defer":
      case "disabled":
      case "disablePictureInPicture":
      case "disableRemotePlayback":
      case "formNoValidate":
      case "hidden":
      case "loop":
      case "noModule":
      case "noValidate":
      case "open":
      case "playsInline":
      case "readOnly":
      case "required":
      case "reversed":
      case "scoped":
      case "seamless":
      case "itemScope":
        a && typeof a != "function" && typeof a != "symbol" ? t.setAttribute(e, "") : t.removeAttribute(e);
        break;
      case "capture":
      case "download":
        a === !0 ? t.setAttribute(e, "") : a !== !1 && a != null && typeof a != "function" && typeof a != "symbol" ? t.setAttribute(e, a) : t.removeAttribute(e);
        break;
      case "cols":
      case "rows":
      case "size":
      case "span":
        a != null && typeof a != "function" && typeof a != "symbol" && !isNaN(a) && 1 <= a ? t.setAttribute(e, a) : t.removeAttribute(e);
        break;
      case "rowSpan":
      case "start":
        a == null || typeof a == "function" || typeof a == "symbol" || isNaN(a) ? t.removeAttribute(e) : t.setAttribute(e, a);
        break;
      case "popover":
        st("beforetoggle", t), st("toggle", t), zn(t, "popover", a);
        break;
      case "xlinkActuate":
        de(
          t,
          "http://www.w3.org/1999/xlink",
          "xlink:actuate",
          a
        );
        break;
      case "xlinkArcrole":
        de(
          t,
          "http://www.w3.org/1999/xlink",
          "xlink:arcrole",
          a
        );
        break;
      case "xlinkRole":
        de(
          t,
          "http://www.w3.org/1999/xlink",
          "xlink:role",
          a
        );
        break;
      case "xlinkShow":
        de(
          t,
          "http://www.w3.org/1999/xlink",
          "xlink:show",
          a
        );
        break;
      case "xlinkTitle":
        de(
          t,
          "http://www.w3.org/1999/xlink",
          "xlink:title",
          a
        );
        break;
      case "xlinkType":
        de(
          t,
          "http://www.w3.org/1999/xlink",
          "xlink:type",
          a
        );
        break;
      case "xmlBase":
        de(
          t,
          "http://www.w3.org/XML/1998/namespace",
          "xml:base",
          a
        );
        break;
      case "xmlLang":
        de(
          t,
          "http://www.w3.org/XML/1998/namespace",
          "xml:lang",
          a
        );
        break;
      case "xmlSpace":
        de(
          t,
          "http://www.w3.org/XML/1998/namespace",
          "xml:space",
          a
        );
        break;
      case "is":
        zn(t, "is", a);
        break;
      case "innerText":
      case "textContent":
        return;
      default:
        if (!(2 < e.length) || e[0] !== "o" && e[0] !== "O" || e[1] !== "n" && e[1] !== "N")
          e = ev.get(e) || e, zn(t, e, a);
        else return;
    }
    vt = !0;
  }
  function fs(t, l, e, a, u, n) {
    switch (e) {
      case "style":
        yo(t, a, n);
        return;
      case "dangerouslySetInnerHTML":
        if (a != null) {
          if (typeof a != "object" || !("__html" in a))
            throw Error(r(61));
          if (e = a.__html, e != null) {
            if (u.children != null) throw Error(r(60));
            n?.__html !== e && (t.innerHTML = e);
          }
        }
        break;
      case "children":
        if (typeof a == "string") Da(t, a);
        else if (typeof a == "number" || typeof a == "bigint")
          Da(t, "" + a);
        else return;
        break;
      case "onScroll":
        a != null && st("scroll", t);
        return;
      case "onScrollEnd":
        a != null && st("scrollend", t);
        return;
      case "onClick":
        a != null && (t.onclick = Pl);
        return;
      case "suppressContentEditableWarning":
      case "suppressHydrationWarning":
      case "innerHTML":
      case "ref":
        return;
      case "innerText":
      case "textContent":
        return;
      default:
        if (!no.hasOwnProperty(e))
          t: {
            if (e[0] === "o" && e[1] === "n" && (u = e.endsWith("Capture"), n = e.slice(2, u ? e.length - 7 : void 0), l = t[vl] || null, l = l != null ? l[e] : null, typeof l == "function" && t.removeEventListener(n, l, u), typeof a == "function")) {
              typeof l != "function" && l !== null && (e in t ? t[e] = null : t.hasAttribute(e) && t.removeAttribute(e)), t.addEventListener(n, a, u);
              break t;
            }
            vt = !0, e in t ? t[e] = a : a === !0 ? t.setAttribute(e, "") : zn(t, e, a);
          }
        return;
    }
    vt = !0;
  }
  function nl(t, l, e) {
    switch (l) {
      case "div":
      case "span":
      case "svg":
      case "path":
      case "a":
      case "g":
      case "p":
      case "li":
        break;
      case "img":
        st("error", t), st("load", t);
        var a = !1, u = !1, n;
        for (n in e)
          if (e.hasOwnProperty(n)) {
            var i = e[n];
            if (i != null)
              switch (n) {
                case "src":
                  a = !0;
                  break;
                case "srcSet":
                  u = !0;
                  break;
                case "children":
                case "dangerouslySetInnerHTML":
                  throw Error(r(137, l));
                default:
                  Nt(t, l, n, i, e, null);
              }
          }
        u && Nt(t, l, "srcSet", e.srcSet, e, null), a && Nt(t, l, "src", e.src, e, null);
        return;
      case "input":
        st("invalid", t);
        var c = n = i = u = null, f = null, y = null;
        for (a in e)
          if (e.hasOwnProperty(a)) {
            var S = e[a];
            if (S != null)
              switch (a) {
                case "name":
                  u = S;
                  break;
                case "type":
                  i = S;
                  break;
                case "checked":
                  f = S;
                  break;
                case "defaultChecked":
                  y = S;
                  break;
                case "value":
                  n = S;
                  break;
                case "defaultValue":
                  c = S;
                  break;
                case "children":
                case "dangerouslySetInnerHTML":
                  if (S != null)
                    throw Error(r(137, l));
                  break;
                default:
                  Nt(t, l, a, S, e, null);
              }
          }
        ro(
          t,
          n,
          c,
          f,
          y,
          i,
          u,
          !1
        );
        return;
      case "select":
        st("invalid", t), a = i = n = null;
        for (u in e)
          if (e.hasOwnProperty(u) && (c = e[u], c != null))
            switch (u) {
              case "value":
                n = c;
                break;
              case "defaultValue":
                i = c;
                break;
              case "multiple":
                a = c;
              default:
                Nt(t, l, u, c, e, null);
            }
        l = n, e = i, t.multiple = !!a, l != null ? Ra(t, !!a, l, !1) : e != null && Ra(t, !!a, e, !0);
        return;
      case "textarea":
        st("invalid", t), n = u = a = null;
        for (i in e)
          if (e.hasOwnProperty(i) && (c = e[i], c != null))
            switch (i) {
              case "value":
                a = c;
                break;
              case "defaultValue":
                u = c;
                break;
              case "children":
                n = c;
                break;
              case "dangerouslySetInnerHTML":
                if (c != null) throw Error(r(91));
                break;
              default:
                Nt(t, l, i, c, e, null);
            }
        vo(t, a, u, n);
        return;
      case "option":
        for (f in e)
          e.hasOwnProperty(f) && (a = e[f], a != null) && (f === "selected" ? t.selected = a && typeof a != "function" && typeof a != "symbol" : Nt(t, l, f, a, e, null));
        return;
      case "dialog":
        st("beforetoggle", t), st("toggle", t), st("cancel", t), st("close", t);
        break;
      case "iframe":
      case "object":
        st("load", t);
        break;
      case "video":
      case "audio":
        for (a = 0; a < tn.length; a++)
          st(tn[a], t);
        break;
      case "image":
        st("error", t), st("load", t);
        break;
      case "details":
        st("toggle", t);
        break;
      case "embed":
      case "source":
      case "link":
        st("error", t), st("load", t);
      case "area":
      case "base":
      case "br":
      case "col":
      case "hr":
      case "keygen":
      case "meta":
      case "param":
      case "track":
      case "wbr":
      case "menuitem":
        for (y in e)
          if (e.hasOwnProperty(y) && (a = e[y], a != null))
            switch (y) {
              case "children":
              case "dangerouslySetInnerHTML":
                throw Error(r(137, l));
              default:
                Nt(t, l, y, a, e, null);
            }
        return;
      default:
        if (sc(l)) {
          for (S in e)
            e.hasOwnProperty(S) && (a = e[S], a !== void 0 && fs(
              t,
              l,
              S,
              a,
              e,
              void 0
            ));
          return;
        }
    }
    for (c in e)
      e.hasOwnProperty(c) && (a = e[c], a != null && Nt(t, l, c, a, e, null));
  }
  var Yh = {};
  function Xh(t, l, e, a) {
    switch (l) {
      case "div":
      case "span":
      case "svg":
      case "path":
      case "a":
      case "g":
      case "p":
      case "li":
        break;
      case "input":
        var u = null, n = null, i = null, c = null, f = null, y = null, S = null;
        for (b in e) {
          var z = e[b];
          if (e.hasOwnProperty(b) && z != null)
            switch (b) {
              case "checked":
                break;
              case "value":
                break;
              case "defaultValue":
                f = z;
              default:
                a.hasOwnProperty(b) || Nt(t, l, b, null, a, z);
            }
        }
        for (var v in a) {
          var b = a[v];
          if (z = e[v], a.hasOwnProperty(v) && (b != null || z != null))
            switch (v) {
              case "type":
                b !== z && (vt = !0), n = b;
                break;
              case "name":
                b !== z && (vt = !0), u = b;
                break;
              case "checked":
                b !== z && (vt = !0), y = b;
                break;
              case "defaultChecked":
                b !== z && (vt = !0), S = b;
                break;
              case "value":
                b !== z && (vt = !0), i = b;
                break;
              case "defaultValue":
                b !== z && (vt = !0), c = b;
                break;
              case "children":
              case "dangerouslySetInnerHTML":
                if (b != null)
                  throw Error(r(137, l));
                break;
              default:
                b !== z && Nt(
                  t,
                  l,
                  v,
                  b,
                  a,
                  z
                );
            }
        }
        cc(
          t,
          i,
          c,
          f,
          y,
          S,
          n,
          u
        );
        return;
      case "select":
        b = i = c = v = null;
        for (n in e)
          if (f = e[n], e.hasOwnProperty(n) && f != null)
            switch (n) {
              case "value":
                break;
              case "multiple":
                b = f;
              default:
                a.hasOwnProperty(n) || Nt(
                  t,
                  l,
                  n,
                  null,
                  a,
                  f
                );
            }
        for (u in a)
          if (n = a[u], f = e[u], a.hasOwnProperty(u) && (n != null || f != null))
            switch (u) {
              case "value":
                n !== f && (vt = !0), v = n;
                break;
              case "defaultValue":
                n !== f && (vt = !0), c = n;
                break;
              case "multiple":
                n !== f && (vt = !0), i = n;
              default:
                n !== f && Nt(
                  t,
                  l,
                  u,
                  n,
                  a,
                  f
                );
            }
        l = c, e = i, a = b, v != null ? Ra(t, !!e, v, !1) : !!a != !!e && (l != null ? Ra(t, !!e, l, !0) : Ra(t, !!e, e ? [] : "", !1));
        return;
      case "textarea":
        b = v = null;
        for (c in e)
          if (u = e[c], e.hasOwnProperty(c) && u != null && !a.hasOwnProperty(c))
            switch (c) {
              case "value":
                break;
              case "children":
                break;
              default:
                Nt(t, l, c, null, a, u);
            }
        for (i in a)
          if (u = a[i], n = e[i], a.hasOwnProperty(i) && (u != null || n != null))
            switch (i) {
              case "value":
                u !== n && (vt = !0), v = u;
                break;
              case "defaultValue":
                u !== n && (vt = !0), b = u;
                break;
              case "children":
                break;
              case "dangerouslySetInnerHTML":
                if (u != null) throw Error(r(91));
                break;
              default:
                u !== n && Nt(t, l, i, u, a, n);
            }
        mo(t, v, b);
        return;
      case "option":
        for (var j in e)
          v = e[j], e.hasOwnProperty(j) && v != null && !a.hasOwnProperty(j) && (j === "selected" ? t.selected = !1 : Nt(
            t,
            l,
            j,
            null,
            a,
            v
          ));
        for (f in a)
          v = a[f], b = e[f], a.hasOwnProperty(f) && v !== b && (v != null || b != null) && (f === "selected" ? (v !== b && (vt = !0), t.selected = v && typeof v != "function" && typeof v != "symbol") : Nt(
            t,
            l,
            f,
            v,
            a,
            b
          ));
        return;
      case "img":
      case "link":
      case "area":
      case "base":
      case "br":
      case "col":
      case "embed":
      case "hr":
      case "keygen":
      case "meta":
      case "param":
      case "source":
      case "track":
      case "wbr":
      case "menuitem":
        for (var Z in e)
          v = e[Z], e.hasOwnProperty(Z) && v != null && !a.hasOwnProperty(Z) && Nt(t, l, Z, null, a, v);
        for (y in a)
          if (v = a[y], b = e[y], a.hasOwnProperty(y) && v !== b && (v != null || b != null))
            switch (y) {
              case "children":
              case "dangerouslySetInnerHTML":
                if (v != null)
                  throw Error(r(137, l));
                break;
              default:
                Nt(
                  t,
                  l,
                  y,
                  v,
                  a,
                  b
                );
            }
        return;
      default:
        if (sc(l)) {
          for (var it in e)
            v = e[it], e.hasOwnProperty(it) && v !== void 0 && !a.hasOwnProperty(it) && fs(
              t,
              l,
              it,
              void 0,
              a,
              v
            );
          for (S in a)
            v = a[S], b = e[S], !a.hasOwnProperty(S) || v === b || v === void 0 && b === void 0 || fs(
              t,
              l,
              S,
              v,
              a,
              b
            );
          return;
        }
    }
    for (var h in e)
      v = e[h], e.hasOwnProperty(h) && v != null && !a.hasOwnProperty(h) && Nt(t, l, h, null, a, v);
    for (z in a)
      v = a[z], b = e[z], !a.hasOwnProperty(z) || v === b || v == null && b == null || Nt(t, l, z, v, a, b);
  }
  function Tm(t) {
    switch (t) {
      case "css":
      case "script":
      case "font":
      case "img":
      case "image":
      case "input":
      case "link":
        return !0;
      default:
        return !1;
    }
  }
  function Gh() {
    if (typeof performance.getEntriesByType == "function") {
      for (var t = 0, l = 0, e = performance.getEntriesByType("resource"), a = 0; a < e.length; a++) {
        var u = e[a], n = u.transferSize, i = u.initiatorType, c = u.duration;
        if (n && c && Tm(i)) {
          for (i = 0, c = u.responseEnd, a += 1; a < e.length; a++) {
            var f = e[a], y = f.startTime;
            if (y > c) break;
            var S = f.transferSize, z = f.initiatorType;
            S && Tm(z) && (f = f.responseEnd, i += S * (f < c ? 1 : (c - y) / (f - y)));
          }
          if (--a, l += 8 * (n + i) / (u.duration / 1e3), t++, 10 < t) break;
        }
      }
      if (0 < t) return l / t / 1e6;
    }
    return navigator.connection && (t = navigator.connection.downlink, typeof t == "number") ? t : 5;
  }
  var ss = null, os = null;
  function en(t) {
    return t.nodeType === 9 ? t : t.ownerDocument;
  }
  function xm(t) {
    switch (t) {
      case "http://www.w3.org/2000/svg":
        return 1;
      case "http://www.w3.org/1998/Math/MathML":
        return 2;
      default:
        return 0;
    }
  }
  function Em(t, l) {
    if (t === 0)
      switch (l) {
        case "svg":
          return 1;
        case "math":
          return 2;
        default:
          return 0;
      }
    return t === 1 && l === "foreignObject" ? 0 : t;
  }
  function Nm(t, l, e, a) {
    return e = en(
      e
    ).createElement(t), e[tl] = a, e[vl] = l, nl(e, t, l), $t(e), e;
  }
  function rs(t, l) {
    return t === "textarea" || t === "noscript" || typeof l.children == "string" || typeof l.children == "number" || typeof l.children == "bigint" || typeof l.dangerouslySetInnerHTML == "object" && l.dangerouslySetInnerHTML !== null && l.dangerouslySetInnerHTML.__html != null;
  }
  var ds = null;
  function Qh() {
    var t = window.event;
    return t && t.type === "popstate" ? t === ds ? !1 : (ds = t, !0) : (ds = null, !1);
  }
  var ms = typeof setTimeout == "function" ? setTimeout : void 0, Lh = typeof clearTimeout == "function" ? clearTimeout : void 0, zm = typeof Promise == "function" ? Promise : void 0, Om = typeof requestAnimationFrame == "function" ? requestAnimationFrame : ms, Zh = typeof queueMicrotask == "function" ? queueMicrotask : typeof zm < "u" ? function(t) {
    return zm.resolve(null).then(t).catch(wh);
  } : ms;
  function wh(t) {
    setTimeout(function() {
      throw t;
    });
  }
  function We(t) {
    return t === "head";
  }
  function Am(t, l) {
    var e = l, a = 0;
    do {
      var u = e.nextSibling;
      if (t.removeChild(e), u && u.nodeType === 8)
        if (e = u.data, e === "/$" || e === "/&") {
          if (a === 0) {
            t.removeChild(u), hu(l);
            return;
          }
          a--;
        } else if (e === "$" || e === "$?" || e === "$~" || e === "$!" || e === "&")
          a++;
        else if (e === "html")
          _s(
            t.ownerDocument.documentElement
          );
        else if (e === "head") {
          e = t.ownerDocument.head, _s(e);
          for (var n = e.firstChild; n; ) {
            var i = n.nextSibling, c = n.nodeName;
            n[pu] || c === "SCRIPT" || c === "STYLE" || c === "LINK" && n.rel.toLowerCase() === "stylesheet" || e.removeChild(n), n = i;
          }
        } else
          e === "body" && _s(t.ownerDocument.body);
      e = u;
    } while (e);
    hu(l);
  }
  function Mm(t, l) {
    var e = t;
    t = 0;
    do {
      var a = e.nextSibling;
      if (e.nodeType === 1 ? l ? (e._stashedDisplay = e.style.display, e.style.display = "none") : (e.style.display = e._stashedDisplay || "", e.getAttribute("style") === "" && e.removeAttribute("style")) : e.nodeType === 3 && (l ? (e._stashedText = e.nodeValue, e.nodeValue = "") : e.nodeValue = e._stashedText || ""), a && a.nodeType === 8)
        if (e = a.data, e === "/$") {
          if (t === 0) break;
          t--;
        } else
          e !== "$" && e !== "$?" && e !== "$~" && e !== "$!" || t++;
      e = a;
    } while (e);
  }
  function Cm(t, l, e) {
    if (l = CSS.escape(l) !== l ? "r-" + btoa(l).replace(/=/g, "") : l, t.style.viewTransitionName = l, e != null && (t.style.viewTransitionClass = e), e = getComputedStyle(t), e.display === "inline") {
      if (l = t.getClientRects(), l.length === 1) var a = 1;
      else
        for (var u = a = 0; u < l.length; u++) {
          var n = l[u];
          0 < n.width && 0 < n.height && a++;
        }
      a === 1 && (t = t.style, t.display = l.length === 1 ? "inline-block" : "block", t.marginTop = "-" + e.paddingTop, t.marginBottom = "-" + e.paddingBottom);
    }
  }
  function Rm(t, l) {
    t = t.style, l = l.style;
    var e = l != null ? l.hasOwnProperty("viewTransitionName") ? l.viewTransitionName : l.hasOwnProperty("view-transition-name") ? l["view-transition-name"] : null : null;
    t.viewTransitionName = e == null || typeof e == "boolean" ? "" : ("" + e).trim(), e = l != null ? l.hasOwnProperty("viewTransitionClass") ? l.viewTransitionClass : l.hasOwnProperty("view-transition-class") ? l["view-transition-class"] : null : null, t.viewTransitionClass = e == null || typeof e == "boolean" ? "" : ("" + e).trim(), t.display === "inline-block" && (l == null ? t.display = t.margin = "" : (e = l.display, t.display = e == null || typeof e == "boolean" ? "" : e, e = l.margin, e != null ? t.margin = e : (e = l.hasOwnProperty("marginTop") ? l.marginTop : l["margin-top"], t.marginTop = e == null || typeof e == "boolean" ? "" : e, l = l.hasOwnProperty("marginBottom") ? l.marginBottom : l["margin-bottom"], t.marginBottom = l == null || typeof l == "boolean" ? "" : l)));
  }
  function Vh(t, l, e) {
    return e = e.ownerDocument.defaultView, {
      rect: t,
      abs: l.position === "absolute" || l.position === "fixed",
      clip: l.clipPath !== "none" || l.overflow !== "visible" || l.filter !== "none" || l.mask !== "none" || l.mask !== "none" || l.borderRadius !== "0px",
      view: 0 <= t.bottom && 0 <= t.right && t.top <= e.innerHeight && t.left <= e.innerWidth
    };
  }
  function vs(t) {
    var l = t.getBoundingClientRect(), e = getComputedStyle(t);
    return Vh(l, e, t);
  }
  function Kh(t) {
    return t.documentElement.clientHeight;
  }
  function Jh(t) {
    this.addEventListener("load", t), this.addEventListener("error", t);
  }
  function kh(t, l, e, a, u, n, i, c, f) {
    var y = l.nodeType === 9 ? l : l.ownerDocument;
    try {
      var S = y.startViewTransition({
        update: function() {
          var v = y.defaultView, b = v.navigation && v.navigation.transition, j = y.fonts.status;
          a();
          var Z = [];
          if (j === "loaded" && (Kh(y), y.fonts.status === "loading" && Z.push(y.fonts.ready)), j = Z.length, t !== null)
            for (var it = t.suspenseyImages, h = 0, d = 0; d < it.length; d++) {
              var g = it[d];
              if (!g.complete) {
                var N = g.getBoundingClientRect();
                if (0 < N.bottom && 0 < N.right && N.top < v.innerHeight && N.left < v.innerWidth) {
                  if (h += Im(g), h > qi) {
                    Z.length = j;
                    break;
                  }
                  g = new Promise(
                    Jh.bind(g)
                  ), Z.push(g);
                }
              }
            }
          if (0 < Z.length)
            return v = Promise.race([
              Promise.all(Z),
              new Promise(function(Q) {
                return setTimeout(Q, 500);
              })
            ]).then(u, u), (b ? Promise.allSettled([b.finished, v]) : v).then(n, n);
          if (u(), b)
            return b.finished.then(
              n,
              n
            );
          n();
        },
        types: e
      });
      y.__reactViewTransition = S;
      var z = [];
      return S.ready.then(
        function() {
          for (var v = y.documentElement.getAnimations({
            subtree: !0
          }), b = 0; b < v.length; b++) {
            var j = v[b], Z = j.effect, it = Z.pseudoElement;
            if (it != null && it.startsWith("::view-transition")) {
              z.push(j), j = Z.getKeyframes();
              for (var h = it = void 0, d = !0, g = 0; g < j.length; g++) {
                var N = j[g], Q = N.width;
                if (it === void 0) it = Q;
                else if (it !== Q) {
                  d = !1;
                  break;
                }
                if (Q = N.height, h === void 0) h = Q;
                else if (h !== Q) {
                  d = !1;
                  break;
                }
                delete N.width, delete N.height, N.transform === "none" && delete N.transform;
              }
              d && it !== void 0 && h !== void 0 && (Z.setKeyframes(j), d = getComputedStyle(
                Z.target,
                Z.pseudoElement
              ), d.width !== it || d.height !== h) && (d = j[0], d.width = it, d.height = h, d = j[j.length - 1], d.width = it, d.height = h, Z.setKeyframes(j));
            }
          }
          i();
        },
        function(v) {
          y.__reactViewTransition === S && (y.__reactViewTransition = null);
          try {
            typeof v == "object" && v !== null && v.name === "InvalidStateError" && (v.message === "View transition was skipped because document visibility state is hidden." || v.message === "Skipping view transition because document visibility state has become hidden." || v.message === "Skipping view transition because viewport size changed." || v.message === "Transition was aborted because of invalid state") && (v = null), v !== null && f(v);
          } finally {
            a(), u(), i();
          }
        }
      ), S.finished.finally(function() {
        for (var v = 0; v < z.length; v++)
          z[v].cancel();
        y.__reactViewTransition === S && (y.__reactViewTransition = null), c();
      }), S;
    } catch {
      return a(), u(), i(), null;
    }
  }
  function Ea(t, l) {
    this._scope = document.documentElement, this._selector = "::view-transition-" + t + "(" + l + ")";
  }
  Ea.prototype.animate = function(t, l) {
    return l = typeof l == "number" ? { duration: l } : ut({}, l), l.pseudoElement = this._selector, this._scope.animate(t, l);
  }, Ea.prototype.getAnimations = function() {
    for (var t = this._scope, l = this._selector, e = t.getAnimations({ subtree: !0 }), a = [], u = 0; u < e.length; u++) {
      var n = e[u].effect;
      n !== null && n.target === t && n.pseudoElement === l && a.push(e[u]);
    }
    return a;
  }, Ea.prototype.getComputedStyle = function() {
    return getComputedStyle(this._scope, this._selector);
  };
  function Dm(t) {
    return {
      name: t,
      group: new Ea("group", t),
      imagePair: new Ea("image-pair", t),
      old: new Ea("old", t),
      new: new Ea("new", t)
    };
  }
  function Cl(t) {
    this._fragmentFiber = t, this._observers = this._eventListeners = null;
  }
  Cl.prototype.addEventListener = function(t, l, e) {
    var a = null, u = null;
    if (!(e != null && typeof e != "boolean" && (a = e.signal || null, a !== null && a.aborted))) {
      this._eventListeners === null && (this._eventListeners = []);
      var n = this._eventListeners;
      if (jm(n, t, l, e) === -1) {
        var i = this, c = l;
        e != null && typeof e != "boolean" && e.once === !0 && (c = function(f) {
          i.removeEventListener(
            t,
            l,
            e
          ), typeof l == "function" ? l.call(this, f) : l.handleEvent(f);
        }), a !== null && (u = i.removeEventListener.bind(
          i,
          t,
          l,
          e
        ), a.addEventListener("abort", u, { once: !0 }), u = a.removeEventListener.bind(a, "abort", u)), a = su(e), n.push({
          type: t,
          listener: l,
          optionsOrUseCapture: e,
          attachedListener: c,
          cleanup: u
        }), p(
          this._fragmentFiber.child,
          !1,
          $h,
          t,
          c,
          a
        );
      }
      this._eventListeners = n;
    }
  };
  function $h(t, l, e, a) {
    return at(t).addEventListener(
      l,
      e,
      a
    ), !1;
  }
  Cl.prototype.removeEventListener = function(t, l, e) {
    var a = this._eventListeners;
    if (a !== null && (l = jm(
      a,
      t,
      l,
      e
    ), l !== -1)) {
      var u = a[l];
      e = u.attachedListener;
      var n = u.cleanup;
      u = su(u.optionsOrUseCapture), p(
        this._fragmentFiber.child,
        !1,
        Wh,
        t,
        e,
        u
      ), a.splice(l, 1), n !== null && n();
    }
  };
  function Wh(t, l, e, a) {
    return at(t).removeEventListener(
      l,
      e,
      a
    ), !1;
  }
  function su(t) {
    return t != null && typeof t != "boolean" && (t.once === !0 || t.signal instanceof AbortSignal) ? { capture: t.capture, passive: t.passive } : t;
  }
  function Um(t) {
    return t == null ? "c=0" : typeof t == "boolean" ? "c=" + (t ? "1" : "0") : "c=" + (t.capture ? "1" : "0");
  }
  function jm(t, l, e, a) {
    if (t.length === 0) return -1;
    a = Um(a);
    for (var u = 0; u < t.length; u++) {
      var n = t[u];
      if (n.type === l && n.listener === e && Um(n.optionsOrUseCapture) === a)
        return u;
    }
    return -1;
  }
  Cl.prototype.dispatchEvent = function(t) {
    var l = U(
      this._fragmentFiber
    );
    if (l === null) return !0;
    l = at(l);
    var e = this._eventListeners;
    if (e !== null && 0 < e.length || !t.bubbles) {
      var a = l.nodeType === 9 ? l.createComment("") : document.createTextNode("");
      if (e)
        for (var u = 0; u < e.length; u++) {
          var n = e[u];
          a.addEventListener(
            n.type,
            n.attachedListener,
            su(n.optionsOrUseCapture)
          );
        }
      if (l.appendChild(a), t = a.dispatchEvent(t), e)
        for (u = 0; u < e.length; u++)
          n = e[u], a.removeEventListener(
            n.type,
            n.attachedListener,
            su(n.optionsOrUseCapture)
          );
      return l.removeChild(a), t;
    }
    return l.dispatchEvent(t);
  }, Cl.prototype.focus = function(t) {
    p(
      this._fragmentFiber.child,
      !0,
      Hm,
      t,
      void 0,
      void 0
    );
  };
  function Hm(t, l) {
    return t.tag === 6 ? !1 : (t = at(t), fy(t, l));
  }
  Cl.prototype.focusLast = function(t) {
    var l = [];
    p(
      this._fragmentFiber.child,
      !0,
      hs,
      l,
      void 0,
      void 0
    );
    for (var e = l.length - 1; 0 <= e && !Hm(l[e], t); e--) ;
  };
  function hs(t, l) {
    return l.push(t), !1;
  }
  Cl.prototype.blur = function() {
    var t = U(
      this._fragmentFiber
    );
    t !== null && (t = at(t), t = en(t).activeElement, t !== null && p(
      this._fragmentFiber.child,
      !1,
      Fh,
      t,
      void 0,
      void 0
    ));
  };
  function Fh(t, l) {
    return t.tag === 6 ? !1 : (t = at(t), t === l || t.contains(l) ? (l.blur(), !0) : !1);
  }
  Cl.prototype.observeUsing = function(t) {
    this._observers === null && (this._observers = /* @__PURE__ */ new Set()), this._observers.add(t), p(
      this._fragmentFiber.child,
      !1,
      Ih,
      t,
      void 0,
      void 0
    );
  };
  function Ih(t, l) {
    return t.tag === 6 || (t = at(t), l.observe(t)), !1;
  }
  Cl.prototype.unobserveUsing = function(t) {
    var l = this._observers;
    if (l !== null && l.has(t)) {
      l.delete(t), p(
        this._fragmentFiber.child,
        !1,
        Ph,
        t,
        void 0,
        void 0
      );
      for (var e = l = 0; e < Wl.length; e++) {
        var a = Wl[e];
        a.fragmentInstance === this && a.observer === t ? t.unobserve(a.instance) : Wl[l++] = a;
      }
      Wl.length = l;
    }
  };
  function Ph(t, l) {
    return t.tag === 6 || (t = at(t), l.unobserve(t)), !1;
  }
  var Wl = [], ys = !1;
  function ty(t, l, e) {
    Wl.push({
      fragmentInstance: t,
      observer: l,
      instance: e
    }), ys || (ys = !0, sy(function() {
      ys = !1;
      var a = Wl;
      Wl = [];
      for (var u = 0; u < a.length; u++) {
        var n = a[u];
        n.observer.unobserve(n.instance);
      }
    }));
  }
  Cl.prototype.getClientRects = function() {
    var t = [];
    return p(
      this._fragmentFiber.child,
      !1,
      ly,
      t,
      void 0,
      void 0
    ), t;
  };
  function ly(t, l) {
    if (t.tag === 6) {
      t = t.stateNode;
      var e = t.ownerDocument.createRange();
      e.selectNodeContents(t), l.push.apply(l, e.getClientRects());
    } else
      t = at(t), l.push.apply(l, t.getClientRects());
    return !1;
  }
  Cl.prototype.getRootNode = function(t) {
    var l = U(
      this._fragmentFiber
    );
    return l === null ? this : at(l).getRootNode(t);
  }, Cl.prototype.compareDocumentPosition = function(t) {
    var l = U(
      this._fragmentFiber
    );
    if (l === null) return Node.DOCUMENT_POSITION_DISCONNECTED;
    var e = [];
    p(
      this._fragmentFiber.child,
      !1,
      hs,
      e,
      void 0,
      void 0
    );
    var a = at(l);
    if (e.length === 0) {
      if (e = a, X(this._fragmentFiber)) {
        t: {
          for (l = this._fragmentFiber.return; l !== null; ) {
            if (l.tag === 4) {
              l = l.stateNode.containerInfo;
              break t;
            }
            if (l.tag === 3 || l.tag === 5 || l.tag === 27)
              break;
            l = l.return;
          }
          l = null;
        }
        l != null && (e = l);
      }
      l = this._fragmentFiber;
      var u = a = e.compareDocumentPosition(t);
      return e === t ? u = Node.DOCUMENT_POSITION_CONTAINS : a & Node.DOCUMENT_POSITION_CONTAINED_BY && (e = G(l)[1], e === null ? u = Node.DOCUMENT_POSITION_PRECEDING : (t = at(e).compareDocumentPosition(
        t
      ), u = t === 0 || t & Node.DOCUMENT_POSITION_FOLLOWING ? Node.DOCUMENT_POSITION_FOLLOWING : Node.DOCUMENT_POSITION_PRECEDING)), u |= Node.DOCUMENT_POSITION_IMPLEMENTATION_SPECIFIC;
    }
    l = at(e[0]), u = at(e[e.length - 1]);
    var n = X(this._fragmentFiber) ? l.parentElement : a;
    if (n == null)
      return Node.DOCUMENT_POSITION_DISCONNECTED;
    a = n.compareDocumentPosition(l) & Node.DOCUMENT_POSITION_CONTAINED_BY, n = n.compareDocumentPosition(u) & Node.DOCUMENT_POSITION_CONTAINED_BY;
    var i = l.compareDocumentPosition(t), c = u.compareDocumentPosition(t), f = i & Node.DOCUMENT_POSITION_CONTAINED_BY || c & Node.DOCUMENT_POSITION_CONTAINED_BY;
    return c = a && n && i & Node.DOCUMENT_POSITION_FOLLOWING && c & Node.DOCUMENT_POSITION_PRECEDING, l = a && l === t || n && u === t || f || c ? Node.DOCUMENT_POSITION_CONTAINED_BY : !a && l === t || !n && u === t ? Node.DOCUMENT_POSITION_IMPLEMENTATION_SPECIFIC : i, l & Node.DOCUMENT_POSITION_DISCONNECTED || l & Node.DOCUMENT_POSITION_IMPLEMENTATION_SPECIFIC || ey(
      l,
      this._fragmentFiber,
      e[0],
      e[e.length - 1],
      t
    ) ? l : Node.DOCUMENT_POSITION_IMPLEMENTATION_SPECIFIC;
  };
  function ey(t, l, e, a, u) {
    var n = aa(u);
    if (t & Node.DOCUMENT_POSITION_CONTAINED_BY) {
      if (e = !!n)
        t: {
          for (; n !== null; ) {
            if (n.tag === 7 && (n === l || n.alternate === l)) {
              e = !0;
              break t;
            }
            n = n.return;
          }
          e = !1;
        }
      return e;
    }
    if (t & Node.DOCUMENT_POSITION_CONTAINS) {
      if (n === null)
        return n = u.ownerDocument, u === n || u === n.documentElement || u === n.body;
      t: {
        for (n = l, l = U(l); n !== null; ) {
          if (!(n.tag !== 5 && n.tag !== 3 && n.tag !== 27 || n !== l && n.alternate !== l)) {
            n = !0;
            break t;
          }
          n = n.return;
        }
        n = !1;
      }
      return n;
    }
    return t & Node.DOCUMENT_POSITION_PRECEDING ? ((l = !!n) && !(l = n === e) && (l = pt(
      e,
      n,
      Mt
    ), l === null ? l = !1 : (p(
      l,
      !0,
      Pt,
      n,
      e
    ), n = Ot, Ot = null, l = n !== null)), l) : t & Node.DOCUMENT_POSITION_FOLLOWING ? ((l = !!n) && !(l = n === a) && (l = pt(
      a,
      n,
      Mt
    ), l === null ? l = !1 : (p(
      l,
      !0,
      St,
      n,
      a
    ), n = Ot, ht = Ot = null, l = n !== null)), l) : !1;
  }
  function Bm(t, l) {
    var e = t.ownerDocument.createRange();
    e.selectNodeContents(t), t = e.getBoundingClientRect(), window.scrollTo(
      window.scrollX + t.left,
      l ? window.scrollY + t.top : window.scrollY + t.bottom - window.innerHeight
    );
  }
  Cl.prototype.scrollIntoView = function(t) {
    if (typeof t == "object") throw Error(r(566));
    var l = [];
    p(
      this._fragmentFiber.child,
      !1,
      hs,
      l,
      void 0,
      void 0
    );
    var e = t !== !1;
    if (l.length === 0) {
      var a = G(
        this._fragmentFiber
      );
      if (a = e ? a[1] || a[0] || U(this._fragmentFiber) : a[0] || a[1], a === null) return;
      if (a.tag === 6) {
        t = at(a), Bm(t, e);
        return;
      }
      if (a = at(a), a.nodeType !== 9) {
        if (a.nodeType === 11) {
          e = "host" in a ? a.host : null, e !== null && e.scrollIntoView(t);
          return;
        }
        a.scrollIntoView(t);
      }
    }
    for (a = e ? l.length - 1 : 0; a !== (e ? -1 : l.length); ) {
      var u = l[a];
      u.tag === 6 ? (u = at(u), Bm(u, e)) : at(u).scrollIntoView(t), a += e ? -1 : 1;
    }
  };
  function ay(t, l) {
    return t = at(t), qm(t, l), !1;
  }
  function qm(t, l) {
    t.reactFragments == null && (t.reactFragments = /* @__PURE__ */ new Set()), t.reactFragments.add(l);
  }
  function Ym(t, l) {
    var e = l._eventListeners;
    if (e !== null)
      for (var a = 0; a < e.length; a++) {
        var u = e[a];
        t.addEventListener(
          u.type,
          u.attachedListener,
          su(u.optionsOrUseCapture)
        );
      }
    t.nodeType !== 3 && (e = l._observers, e !== null && e.forEach(function(n) {
      for (var i = 0, c = 0; c < Wl.length; c++) {
        var f = Wl[c];
        (f.fragmentInstance !== l || f.observer !== n || f.instance !== t) && (Wl[i++] = f);
      }
      Wl.length = i, n.observe(t);
    }), qm(t, l));
  }
  function uy(t, l) {
    var e = l._eventListeners;
    if (e !== null)
      for (var a = 0; a < e.length; a++) {
        var u = e[a];
        t.removeEventListener(
          u.type,
          u.attachedListener,
          su(u.optionsOrUseCapture)
        );
      }
    t.nodeType !== 3 && (e = l._observers, e !== null && e.forEach(function(n) {
      typeof n.rootMargin == "string" ? ty(
        l,
        n,
        t
      ) : n.unobserve(t);
    }), t.reactFragments != null && t.reactFragments.delete(l));
  }
  function gs(t) {
    var l = t.firstChild;
    for (l && l.nodeType === 10 && (l = l.nextSibling); l; ) {
      var e = l;
      switch (l = l.nextSibling, e.nodeName) {
        case "HTML":
        case "HEAD":
        case "BODY":
          gs(e), Nn(e);
          continue;
        case "SCRIPT":
        case "STYLE":
          continue;
        case "LINK":
          if (e.rel.toLowerCase() === "stylesheet") continue;
      }
      t.removeChild(e);
    }
  }
  function ny(t, l, e, a) {
    for (; t.nodeType === 1; ) {
      var u = e;
      if (t.nodeName.toLowerCase() !== l.toLowerCase()) {
        if (!a && (t.nodeName !== "INPUT" || t.type !== "hidden"))
          break;
      } else if (a) {
        if (!t[pu])
          switch (l) {
            case "meta":
              if (!t.hasAttribute("itemprop")) break;
              return t;
            case "link":
              if (n = t.getAttribute("rel"), n === "stylesheet" && t.hasAttribute("data-precedence"))
                break;
              if (n !== u.rel || t.getAttribute("href") !== (u.href == null || u.href === "" ? null : u.href) || t.getAttribute("crossorigin") !== (u.crossOrigin == null ? null : u.crossOrigin) || t.getAttribute("title") !== (u.title == null ? null : u.title))
                break;
              return t;
            case "style":
              if (t.hasAttribute("data-precedence")) break;
              return t;
            case "script":
              if (n = t.getAttribute("src"), (n !== (u.src == null ? null : u.src) || t.getAttribute("type") !== (u.type == null ? null : u.type) || t.getAttribute("crossorigin") !== (u.crossOrigin == null ? null : u.crossOrigin)) && n && t.hasAttribute("async") && !t.hasAttribute("itemprop"))
                break;
              return t;
            default:
              return t;
          }
      } else if (l === "input" && t.type === "hidden") {
        var n = u.name == null ? null : "" + u.name;
        if (u.type === "hidden" && t.getAttribute("name") === n)
          return t;
      } else return t;
      if (t = Gl(t.nextSibling), t === null) break;
    }
    return null;
  }
  function iy(t, l, e) {
    if (l === "") return null;
    for (; t.nodeType !== 3; )
      if ((t.nodeType !== 1 || t.nodeName !== "INPUT" || t.type !== "hidden") && !e || (t = Gl(t.nextSibling), t === null)) return null;
    return t;
  }
  function Xm(t, l) {
    for (; t.nodeType !== 8; )
      if ((t.nodeType !== 1 || t.nodeName !== "INPUT" || t.type !== "hidden") && !l || (t = Gl(t.nextSibling), t === null)) return null;
    return t;
  }
  function bs(t) {
    return t.data === "$?" || t.data === "$~";
  }
  function Ss(t) {
    return t.data === "$!" || t.data === "$?" && t.ownerDocument.readyState !== "loading";
  }
  function cy(t, l) {
    var e = t.ownerDocument;
    if (t.data === "$~") t._reactRetry = l;
    else if (t.data !== "$?" || e.readyState !== "loading")
      l();
    else {
      var a = function() {
        l(), e.removeEventListener("DOMContentLoaded", a);
      };
      e.addEventListener("DOMContentLoaded", a), t._reactRetry = a;
    }
  }
  function Gl(t) {
    for (; t != null; t = t.nextSibling) {
      var l = t.nodeType;
      if (l === 1 || l === 3) break;
      if (l === 8) {
        if (l = t.data, l === "$" || l === "$!" || l === "$?" || l === "$~" || l === "&" || l === "F!" || l === "F")
          break;
        if (l === "/$" || l === "/&") return null;
      }
    }
    return t;
  }
  var ps = null;
  function Gm(t) {
    t = t.nextSibling;
    for (var l = 0; t; ) {
      if (t.nodeType === 8) {
        var e = t.data;
        if (e === "/$" || e === "/&") {
          if (l === 0)
            return Gl(t.nextSibling);
          l--;
        } else
          e !== "$" && e !== "$!" && e !== "$?" && e !== "$~" && e !== "&" || l++;
      }
      t = t.nextSibling;
    }
    return null;
  }
  function Qm(t) {
    t = t.previousSibling;
    for (var l = 0; t; ) {
      if (t.nodeType === 8) {
        var e = t.data;
        if (e === "$" || e === "$!" || e === "$?" || e === "$~" || e === "&") {
          if (l === 0) return t;
          l--;
        } else e !== "/$" && e !== "/&" || l++;
      }
      t = t.previousSibling;
    }
    return null;
  }
  function fy(t, l) {
    function e() {
      a = !0;
    }
    if (t.ownerDocument.activeElement === t) return !0;
    var a = !1;
    try {
      t.ownerDocument.addEventListener("focus", e, !0), (t.focus || HTMLElement.prototype.focus).call(t, l);
    } finally {
      t.ownerDocument.removeEventListener("focus", e, !0);
    }
    return a;
  }
  function sy(t) {
    Om(function() {
      Om(function(l) {
        return t(l);
      });
    });
  }
  function Lm(t, l, e) {
    switch (l = en(e), t) {
      case "html":
        if (t = l.documentElement, !t) throw Error(r(452));
        return t;
      case "head":
        if (t = l.head, !t) throw Error(r(453));
        return t;
      case "body":
        if (t = l.body, !t) throw Error(r(454));
        return t;
      default:
        throw Error(r(451));
    }
  }
  function Zm(t, l, e) {
    for (var a in e) {
      var u = e[a];
      e.hasOwnProperty(a) && u != null && Nt(t, l, a, null, Yh, u);
    }
    e.dangerouslySetInnerHTML != null && (t.textContent = ""), t.onclick === Pl && (t.onclick = null), Nn(t);
  }
  function _s(t) {
    for (var l = t.attributes; l.length; )
      t.removeAttributeNode(l[0]);
    Nn(t);
  }
  var Ql = /* @__PURE__ */ new Map(), wm = /* @__PURE__ */ new Set();
  function an(t) {
    if (typeof t.getRootNode == "function") {
      var l = t.getRootNode();
      if (l.nodeType === 9 || l.nodeType === 11) return l;
    }
    return t.nodeType === 9 ? t : t.ownerDocument;
  }
  var Ne = V.d;
  V.d = {
    f: oy,
    r: ry,
    D: dy,
    C: my,
    L: vy,
    m: hy,
    X: gy,
    S: yy,
    M: by
  };
  function oy() {
    var t = Ne.f(), l = Ai();
    return t || l;
  }
  function ry(t) {
    var l = Aa(t);
    l !== null && l.tag === 5 && l.type === "form" ? Kr(l) : Ne.r(t);
  }
  var ou = typeof document > "u" ? null : document;
  function Vm(t, l, e) {
    var a = ou;
    if (a && typeof l == "string" && l) {
      var u = Ul(l);
      u = 'link[rel="' + t + '"][href="' + u + '"]', typeof e == "string" && (u += '[crossorigin="' + e + '"]'), wm.has(u) || (wm.add(u), t = { rel: t, crossOrigin: e, href: l }, a.querySelector(u) === null && (l = a.createElement("link"), nl(l, "link", t), $t(l), a.head.appendChild(l)));
    }
  }
  function dy(t) {
    Ne.D(t), Vm("dns-prefetch", t, null);
  }
  function my(t, l) {
    Ne.C(t, l), Vm("preconnect", t, l);
  }
  function vy(t, l, e) {
    Ne.L(t, l, e);
    var a = ou;
    if (a && t && l) {
      var u = 'link[rel="preload"][as="' + Ul(l) + '"]';
      l === "image" && e && e.imageSrcSet ? (u += '[imagesrcset="' + Ul(
        e.imageSrcSet
      ) + '"]', typeof e.imageSizes == "string" && (u += '[imagesizes="' + Ul(
        e.imageSizes
      ) + '"]')) : u += '[href="' + Ul(t) + '"]';
      var n = u;
      switch (l) {
        case "style":
          n = ru(t);
          break;
        case "script":
          n = du(t);
      }
      if (!(Ql.has(n) || (t = ut(
        {
          rel: "preload",
          href: l === "image" && e && e.imageSrcSet ? void 0 : t,
          as: l
        },
        e
      ), Ql.set(n, t), a.querySelector(u) !== null || l === "style" && a.querySelector(un(n)) || l === "script" && a.querySelector(nn(n))))) {
        var i = a.createElement("link");
        nl(i, "link", t), l === "style" && (i[En] = !0, i.onload = i.onerror = function() {
          ao(i);
        }), $t(i), a.head.appendChild(i);
      }
    }
  }
  function hy(t, l) {
    Ne.m(t, l);
    var e = ou;
    if (e && t) {
      var a = l && typeof l.as == "string" ? l.as : "script", u = 'link[rel="modulepreload"][as="' + Ul(a) + '"][href="' + Ul(t) + '"]', n = u;
      switch (a) {
        case "audioworklet":
        case "paintworklet":
        case "serviceworker":
        case "sharedworker":
        case "worker":
        case "script":
          n = du(t);
      }
      if (!Ql.has(n) && (t = ut({ rel: "modulepreload", href: t }, l), Ql.set(n, t), e.querySelector(u) === null)) {
        switch (a) {
          case "audioworklet":
          case "paintworklet":
          case "serviceworker":
          case "sharedworker":
          case "worker":
          case "script":
            if (e.querySelector(nn(n)))
              return;
        }
        a = e.createElement("link"), nl(a, "link", t), $t(a), e.head.appendChild(a);
      }
    }
  }
  function yy(t, l, e) {
    Ne.S(t, l, e);
    var a = ou;
    if (a && t) {
      var u = Ma(a).hoistableStyles, n = ru(t);
      l = l || "default";
      var i = u.get(n);
      if (!i) {
        var c = { loading: 0, preload: null };
        if (i = a.querySelector(
          un(n)
        ))
          c.loading = 5;
        else {
          t = ut(
            { rel: "stylesheet", href: t, "data-precedence": l },
            e
          ), (e = Ql.get(n)) && Ts(t, e);
          var f = i = a.createElement("link");
          $t(f), nl(f, "link", t), f._p = new Promise(function(y, S) {
            f.onload = y, f.onerror = S;
          }), f.addEventListener("load", function() {
            c.loading |= 1;
          }), f.addEventListener("error", function() {
            c.loading |= 2;
          }), c.loading |= 4, Hi(i, l, a);
        }
        i = {
          type: "stylesheet",
          instance: i,
          count: 1,
          state: c
        }, u.set(n, i);
      }
    }
  }
  function gy(t, l) {
    Ne.X(t, l);
    var e = ou;
    if (e && t) {
      var a = Ma(e).hoistableScripts, u = du(t), n = a.get(u);
      n || (n = e.querySelector(nn(u)), n || (t = ut({ src: t, async: !0 }, l), (l = Ql.get(u)) && xs(t, l), n = e.createElement("script"), $t(n), nl(n, "link", t), e.head.appendChild(n)), n = {
        type: "script",
        instance: n,
        count: 1,
        state: null
      }, a.set(u, n));
    }
  }
  function by(t, l) {
    Ne.M(t, l);
    var e = ou;
    if (e && t) {
      var a = Ma(e).hoistableScripts, u = du(t), n = a.get(u);
      n || (n = e.querySelector(nn(u)), n || (t = ut({ src: t, async: !0, type: "module" }, l), (l = Ql.get(u)) && xs(t, l), n = e.createElement("script"), $t(n), nl(n, "link", t), e.head.appendChild(n)), n = {
        type: "script",
        instance: n,
        count: 1,
        state: null
      }, a.set(u, n));
    }
  }
  function Km(t, l, e, a) {
    var u = (u = Oe.current) ? an(u) : null;
    if (!u) throw Error(r(446));
    switch (t) {
      case "meta":
      case "title":
        return null;
      case "style":
        return typeof e.precedence == "string" && typeof e.href == "string" ? (e = ru(e.href), l = Ma(
          u
        ).hoistableStyles, a = l.get(e), a || (a = {
          type: "style",
          instance: null,
          count: 0,
          state: null
        }, l.set(e, a)), a) : { type: "void", instance: null, count: 0, state: null };
      case "link":
        if (e.rel === "stylesheet" && typeof e.href == "string" && typeof e.precedence == "string") {
          t = ru(e.href);
          var n = Ma(
            u
          ).hoistableStyles, i = n.get(t);
          if (i || (u = u.ownerDocument || u, i = {
            type: "stylesheet",
            instance: null,
            count: 0,
            state: { loading: 0, preload: null }
          }, n.set(t, i), (n = u.querySelector(
            un(t)
          )) ? n._p || (i.instance = n, i.state.loading = 5) : (n = Ql.get(t), n || (n = {
            rel: "preload",
            as: "style",
            href: e.href,
            crossOrigin: e.crossOrigin,
            integrity: e.integrity,
            media: e.media,
            hrefLang: e.hrefLang,
            referrerPolicy: e.referrerPolicy
          }, Ql.set(t, n)), Sy(
            u,
            t,
            n,
            i.state
          ))), l && a === null)
            throw Error(r(528, ""));
          return i;
        }
        if (l && a !== null)
          throw Error(r(529, ""));
        return null;
      case "script":
        return l = e.async, e = e.src, typeof e == "string" && l && typeof l != "function" && typeof l != "symbol" ? (e = du(e), l = Ma(
          u
        ).hoistableScripts, a = l.get(e), a || (a = {
          type: "script",
          instance: null,
          count: 0,
          state: null
        }, l.set(e, a)), a) : { type: "void", instance: null, count: 0, state: null };
      default:
        throw Error(r(444, t));
    }
  }
  function ru(t) {
    return 'href="' + Ul(t) + '"';
  }
  function un(t) {
    return 'link[rel="stylesheet"][' + t + "]";
  }
  function Jm(t) {
    return ut({}, t, {
      "data-precedence": t.precedence,
      precedence: null
    });
  }
  function Sy(t, l, e, a) {
    if (l = t.querySelector(
      'link[rel="preload"][as="style"][' + l + "]"
    )) {
      if (l[En] !== !0) {
        a.loading = 1;
        return;
      }
    } else
      l = t.createElement("link"), l[En] = !0, l.onload = l.onerror = ao.bind(null, l), nl(l, "link", e), $t(l), t.head.appendChild(l);
    a.preload = l, l.addEventListener("load", function() {
      return a.loading |= 1;
    }), l.addEventListener("error", function() {
      return a.loading |= 2;
    });
  }
  function du(t) {
    return '[src="' + Ul(t) + '"]';
  }
  function nn(t) {
    return "script[async]" + t;
  }
  function km(t, l, e) {
    if (l.count++, l.instance === null)
      switch (l.type) {
        case "style":
          var a = t.querySelector(
            'style[data-href~="' + Ul(e.href) + '"]'
          );
          if (a)
            return l.instance = a, $t(a), a;
          var u = ut({}, e, {
            "data-href": e.href,
            "data-precedence": e.precedence,
            href: null,
            precedence: null
          });
          return a = (t.ownerDocument || t).createElement(
            "style"
          ), $t(a), nl(a, "style", u), Hi(a, e.precedence, t), l.instance = a;
        case "stylesheet":
          u = ru(e.href);
          var n = t.querySelector(
            un(u)
          );
          if (n)
            return l.state.loading |= 4, l.instance = n, $t(n), n;
          a = Jm(e), (u = Ql.get(u)) && Ts(a, u), n = (t.ownerDocument || t).createElement("link"), $t(n);
          var i = n;
          return i._p = new Promise(function(c, f) {
            i.onload = c, i.onerror = f;
          }), nl(n, "link", a), l.state.loading |= 4, Hi(n, e.precedence, t), l.instance = n;
        case "script":
          return n = du(e.src), (u = t.querySelector(
            nn(n)
          )) ? (l.instance = u, $t(u), u) : (a = e, (u = Ql.get(n)) && (a = ut({}, e), xs(a, u)), t = t.ownerDocument || t, u = t.createElement("script"), $t(u), nl(u, "link", a), t.head.appendChild(u), l.instance = u);
        case "void":
          return null;
        default:
          throw Error(r(443, l.type));
      }
    else
      l.type === "stylesheet" && (l.state.loading & 4) === 0 && (a = l.instance, l.state.loading |= 4, Hi(a, e.precedence, t));
    return l.instance;
  }
  function Hi(t, l, e) {
    for (var a = e.querySelectorAll(
      'link[rel="stylesheet"][data-precedence],style[data-precedence]'
    ), u = a.length ? a[a.length - 1] : null, n = u, i = 0; i < a.length; i++) {
      var c = a[i];
      if (c.dataset.precedence === l) n = c;
      else if (n !== u) break;
    }
    n ? n.parentNode.insertBefore(t, n.nextSibling) : (l = e.nodeType === 9 ? e.head : e, l.insertBefore(t, l.firstChild));
  }
  function Ts(t, l) {
    t.crossOrigin == null && (t.crossOrigin = l.crossOrigin), t.referrerPolicy == null && (t.referrerPolicy = l.referrerPolicy), t.title == null && (t.title = l.title);
  }
  function xs(t, l) {
    t.crossOrigin == null && (t.crossOrigin = l.crossOrigin), t.referrerPolicy == null && (t.referrerPolicy = l.referrerPolicy), t.integrity == null && (t.integrity = l.integrity);
  }
  var Bi = null;
  function $m(t, l, e) {
    if (Bi === null) {
      var a = /* @__PURE__ */ new Map(), u = Bi = /* @__PURE__ */ new Map();
      u.set(e, a);
    } else
      u = Bi, a = u.get(e), a || (a = /* @__PURE__ */ new Map(), u.set(e, a));
    if (a.has(t)) return a;
    for (a.set(t, null), e = e.getElementsByTagName(t), u = 0; u < e.length; u++) {
      var n = e[u];
      if (!(n[pu] || n[tl] || t === "link" && n.getAttribute("rel") === "stylesheet") && n.namespaceURI !== "http://www.w3.org/2000/svg") {
        var i = n.getAttribute(l) || "";
        i = t + i;
        var c = a.get(i);
        c ? c.push(n) : a.set(i, [n]);
      }
    }
    return a;
  }
  function Es(t, l, e) {
    t = t.ownerDocument || t, t.head.insertBefore(
      e,
      l === "title" ? t.querySelector("head > title") : null
    );
  }
  function py(t, l, e) {
    if (e === 1 || l.itemProp != null) return !1;
    switch (t) {
      case "meta":
      case "title":
        return !0;
      case "style":
        if (typeof l.precedence != "string" || typeof l.href != "string" || l.href === "")
          break;
        return !0;
      case "link":
        if (typeof l.rel != "string" || typeof l.href != "string" || l.href === "" || l.onLoad || l.onError)
          break;
        return l.rel === "stylesheet" ? (t = l.disabled, typeof l.precedence == "string" && t == null) : !0;
      case "script":
        if (l.async && typeof l.async != "function" && typeof l.async != "symbol" && !l.onLoad && !l.onError && l.src && typeof l.src == "string")
          return !0;
    }
    return !1;
  }
  function Wm(t, l) {
    return t === "img" && l.src != null && l.src !== "" && l.onLoad == null && l.loading !== "lazy";
  }
  function Fm(t) {
    return !(t.type === "stylesheet" && (t.state.loading & 3) === 0);
  }
  function Im(t) {
    return (t.width || 100) * (t.height || 100) * (typeof devicePixelRatio == "number" ? devicePixelRatio : 1) * 0.25;
  }
  function Pm(t, l) {
    typeof l.decode == "function" && (t.imgCount++, l.complete || (t.imgBytes += Im(l), t.suspenseyImages.push(l)), t = xy.bind(t), l.decode().then(t, t));
  }
  function _y(t, l, e, a) {
    if (e.type === "stylesheet" && (typeof a.media != "string" || matchMedia(a.media).matches !== !1) && (e.state.loading & 4) === 0) {
      if (e.instance === null) {
        var u = ru(a.href), n = l.querySelector(
          un(u)
        );
        if (n) {
          l = n._p, l !== null && typeof l == "object" && typeof l.then == "function" && (t.count++, t = cn.bind(t), l.then(t, t)), e.state.loading |= 4, e.instance = n, $t(n);
          return;
        }
        n = l.ownerDocument || l, a = Jm(a), (u = Ql.get(u)) && Ts(a, u), n = n.createElement("link"), $t(n);
        var i = n;
        i._p = new Promise(function(c, f) {
          i.onload = c, i.onerror = f;
        }), nl(n, "link", a), e.instance = n;
      }
      t.stylesheets === null && (t.stylesheets = /* @__PURE__ */ new Map()), t.stylesheets.set(e, l), (l = e.state.preload) && (e.state.loading & 3) === 0 && (t.count++, e = cn.bind(t), l.addEventListener("load", e), l.addEventListener("error", e));
    }
  }
  var qi = 0;
  function Ty(t, l) {
    return t.stylesheets && t.count === 0 && Xi(t, t.stylesheets), 0 < t.count || 0 < t.imgCount ? function(e) {
      var a = setTimeout(function() {
        if (t.stylesheets && Xi(t, t.stylesheets), t.unsuspend) {
          var n = t.unsuspend;
          t.unsuspend = null, n();
        }
      }, 6e4 + l);
      0 < t.imgBytes && qi === 0 && (qi = 62500 * Gh());
      var u = setTimeout(
        function() {
          if (t.waitingForImages = !1, t.count === 0 && (t.stylesheets && Xi(t, t.stylesheets), t.unsuspend)) {
            var n = t.unsuspend;
            t.unsuspend = null, n();
          }
        },
        (t.imgBytes > qi ? 50 : 800) + l
      );
      return t.unsuspend = e, function() {
        t.unsuspend = null, clearTimeout(a), clearTimeout(u);
      };
    } : null;
  }
  function t0(t) {
    if (t.count === 0 && (t.imgCount === 0 || !t.waitingForImages)) {
      if (t.stylesheets) Xi(t, t.stylesheets);
      else if (t.unsuspend) {
        var l = t.unsuspend;
        t.unsuspend = null, l();
      }
    }
  }
  function cn() {
    this.count--, t0(this);
  }
  function xy() {
    this.imgCount--, t0(this);
  }
  var Yi = null;
  function Xi(t, l) {
    t.stylesheets = null, t.unsuspend !== null && (t.count++, Yi = /* @__PURE__ */ new Map(), l.forEach(Ey, t), Yi = null, cn.call(t));
  }
  function Ey(t, l) {
    if (!(l.state.loading & 4)) {
      var e = Yi.get(t);
      if (e) var a = e.get(null);
      else {
        e = /* @__PURE__ */ new Map(), Yi.set(t, e);
        for (var u = t.querySelectorAll(
          "link[data-precedence],style[data-precedence]"
        ), n = 0; n < u.length; n++) {
          var i = u[n];
          (i.nodeName === "LINK" || i.getAttribute("media") !== "not all") && (e.set(i.dataset.precedence, i), a = i);
        }
        a && e.set(null, a);
      }
      u = l.instance, i = u.getAttribute("data-precedence"), n = e.get(i) || a, n === a && e.set(null, u), e.set(i, u), this.count++, a = cn.bind(this), u.addEventListener("load", a), u.addEventListener("error", a), n ? n.parentNode.insertBefore(u, n.nextSibling) : (t = t.nodeType === 9 ? t.head : t, t.insertBefore(u, t.firstChild)), l.state.loading |= 4;
    }
  }
  var mu = {
    $$typeof: Yt,
    Provider: null,
    Consumer: null,
    _currentValue: Ut,
    _currentValue2: Ut,
    _threadCount: 0
  };
  function Ny(t, l, e, a, u, n, i, c, f) {
    this.tag = 1, this.containerInfo = t, this.pingCache = this.current = this.pendingChildren = null, this.timeoutHandle = -1, this.callbackNode = this.next = this.pendingContext = this.context = this.cancelPendingCommit = null, this.callbackPriority = 0, this.expirationTimes = ac(-1), this.entangledLanes = this.shellSuspendCounter = this.errorRecoveryDisabledLanes = this.expiredLanes = this.warmLanes = this.pingedLanes = this.suspendedLanes = this.pendingLanes = 0, this.entanglements = ac(0), this.hiddenUpdates = ac(null), this.identifierPrefix = a, this.onUncaughtError = u, this.onCaughtError = n, this.onRecoverableError = i, this.pooledCache = null, this.pooledCacheLanes = 0, this.formState = f, this.transitionTypes = null, this.incompleteTransitions = /* @__PURE__ */ new Map();
  }
  function l0(t, l, e, a, u, n, i, c, f, y, S, z) {
    return t = new Ny(
      t,
      l,
      e,
      i,
      f,
      y,
      S,
      z,
      c
    ), l = 1, n === !0 && (l |= 24), n = hl(3, null, null, l), t.current = n, n.stateNode = t, l = Yc(), l.refCount++, t.pooledCache = l, l.refCount++, n.memoizedState = {
      element: a,
      isDehydrated: e,
      cache: l
    }, Lc(n), t;
  }
  function e0(t) {
    return t ? (t = Xa, t) : Xa;
  }
  function a0(t, l, e, a, u, n) {
    u = e0(u), a.context === null ? a.context = u : a.pendingContext = u, a = Ye(l), a.payload = { element: e }, n = n === void 0 ? null : n, n !== null && (a.callback = n), e = Xe(t, a, l), e !== null && (Sl(e, t, l), qu(e, t, l));
  }
  function u0(t, l) {
    if (t = t.memoizedState, t !== null && t.dehydrated !== null) {
      var e = t.retryLane;
      t.retryLane = e !== 0 && e < l ? e : l;
    }
  }
  function Ns(t, l) {
    u0(t, l), (t = t.alternate) && u0(t, l);
  }
  function n0(t) {
    if (t.tag === 13 || t.tag === 31) {
      var l = ca(t, 67108864);
      l !== null && Sl(l, t, 67108864), Ns(t, 67108864);
    }
  }
  function i0(t) {
    if (t.tag === 13 || t.tag === 31) {
      var l = Ml();
      l = uc(l);
      var e = ca(t, l);
      e !== null && Sl(e, t, l), Ns(t, l);
    }
  }
  var vu = !0;
  function zy(t, l, e, a) {
    var u = H.T;
    H.T = null;
    var n = V.p;
    try {
      V.p = 2, zs(t, l, e, a);
    } finally {
      V.p = n, H.T = u;
    }
  }
  function Oy(t, l, e, a) {
    var u = H.T;
    H.T = null;
    var n = V.p;
    try {
      V.p = 8, zs(t, l, e, a);
    } finally {
      V.p = n, H.T = u;
    }
  }
  function zs(t, l, e, a) {
    if (vu) {
      var u = Os(a);
      if (u === null)
        cs(
          t,
          l,
          a,
          Gi,
          e
        ), f0(t, a);
      else if (My(
        u,
        t,
        l,
        e,
        a
      ))
        a.stopPropagation();
      else if (f0(t, a), l & 4 && -1 < Ay.indexOf(t)) {
        for (; u !== null; ) {
          var n = Aa(u);
          if (n !== null)
            switch (n.tag) {
              case 3:
                if (n = n.stateNode, n.current.memoizedState.isDehydrated) {
                  var i = ea(n.pendingLanes);
                  if (i !== 0) {
                    var c = n;
                    for (c.pendingLanes |= 2, c.entangledLanes |= 2; i; ) {
                      var f = 1 << 31 - Tl(i);
                      c.entanglements[1] |= f, i &= ~f;
                    }
                    se(n), (yt & 6) === 0 && (Ni = pl() + 500, Pu(0));
                  }
                }
                break;
              case 31:
              case 13:
                c = ca(n, 2), c !== null && Sl(c, n, 2), Ai(), Ns(n, 2);
            }
          if (n = Os(a), n === null && cs(
            t,
            l,
            a,
            Gi,
            e
          ), n === u) break;
          u = n;
        }
        u !== null && a.stopPropagation();
      } else
        cs(
          t,
          l,
          a,
          null,
          e
        );
    }
  }
  function Os(t) {
    return t = rc(t), As(t);
  }
  var Gi = null;
  function As(t) {
    if (Gi = null, t = aa(t), t !== null) {
      var l = J(t);
      if (l === null) t = null;
      else {
        var e = l.tag;
        if (e === 13) {
          if (t = M(l), t !== null) return t;
          t = null;
        } else if (e === 31) {
          if (t = A(l), t !== null) return t;
          t = null;
        } else if (e === 3) {
          if (l.stateNode.current.memoizedState.isDehydrated)
            return l.tag === 3 ? l.stateNode.containerInfo : null;
          t = null;
        } else l !== t && (t = null);
      }
    }
    return Gi = t, null;
  }
  function c0(t) {
    switch (t) {
      case "beforetoggle":
      case "cancel":
      case "click":
      case "close":
      case "contextmenu":
      case "copy":
      case "cut":
      case "auxclick":
      case "dblclick":
      case "dragend":
      case "dragstart":
      case "drop":
      case "focusin":
      case "focusout":
      case "input":
      case "invalid":
      case "keydown":
      case "keypress":
      case "keyup":
      case "mousedown":
      case "mouseup":
      case "paste":
      case "pause":
      case "play":
      case "pointercancel":
      case "pointerdown":
      case "pointerup":
      case "ratechange":
      case "reset":
      case "seeked":
      case "submit":
      case "toggle":
      case "touchcancel":
      case "touchend":
      case "touchstart":
      case "volumechange":
      case "change":
      case "selectionchange":
      case "textInput":
      case "compositionstart":
      case "compositionend":
      case "compositionupdate":
      case "beforeblur":
      case "afterblur":
      case "beforeinput":
      case "blur":
      case "fullscreenchange":
      case "fullscreenerror":
      case "focus":
      case "hashchange":
      case "popstate":
      case "select":
      case "selectstart":
        return 2;
      case "drag":
      case "dragenter":
      case "dragexit":
      case "dragleave":
      case "dragover":
      case "mousemove":
      case "mouseout":
      case "mouseover":
      case "pointermove":
      case "pointerout":
      case "pointerover":
      case "resize":
      case "scroll":
      case "touchmove":
      case "wheel":
      case "mouseenter":
      case "mouseleave":
      case "pointerenter":
      case "pointerleave":
        return 8;
      case "message":
        switch (G0()) {
          case Vs:
            return 2;
          case Ks:
            return 8;
          case Sn:
          case Q0:
            return 32;
          case Js:
            return 268435456;
          default:
            return 32;
        }
      default:
        return 32;
    }
  }
  var Ms = !1, Fe = null, Ie = null, Pe = null, fn = /* @__PURE__ */ new Map(), sn = /* @__PURE__ */ new Map(), ta = [], Ay = "mousedown mouseup touchcancel touchend touchstart auxclick dblclick pointercancel pointerdown pointerup dragend dragstart drop compositionend compositionstart keydown keypress keyup input textInput copy cut paste click change contextmenu reset".split(
    " "
  );
  function f0(t, l) {
    switch (t) {
      case "focusin":
      case "focusout":
        Fe = null;
        break;
      case "dragenter":
      case "dragleave":
        Ie = null;
        break;
      case "mouseover":
      case "mouseout":
        Pe = null;
        break;
      case "pointerover":
      case "pointerout":
        fn.delete(l.pointerId);
        break;
      case "gotpointercapture":
      case "lostpointercapture":
        sn.delete(l.pointerId);
    }
  }
  function on(t, l, e, a, u, n) {
    return t === null || t.nativeEvent !== n ? (t = {
      blockedOn: l,
      domEventName: e,
      eventSystemFlags: a,
      nativeEvent: n,
      targetContainers: [u]
    }, l !== null && (l = Aa(l), l !== null && n0(l)), t) : (t.eventSystemFlags |= a, l = t.targetContainers, u !== null && l.indexOf(u) === -1 && l.push(u), t);
  }
  function My(t, l, e, a, u) {
    switch (l) {
      case "focusin":
        return Fe = on(
          Fe,
          t,
          l,
          e,
          a,
          u
        ), !0;
      case "dragenter":
        return Ie = on(
          Ie,
          t,
          l,
          e,
          a,
          u
        ), !0;
      case "mouseover":
        return Pe = on(
          Pe,
          t,
          l,
          e,
          a,
          u
        ), !0;
      case "pointerover":
        var n = u.pointerId;
        return fn.set(
          n,
          on(
            fn.get(n) || null,
            t,
            l,
            e,
            a,
            u
          )
        ), !0;
      case "gotpointercapture":
        return n = u.pointerId, sn.set(
          n,
          on(
            sn.get(n) || null,
            t,
            l,
            e,
            a,
            u
          )
        ), !0;
    }
    return !1;
  }
  function s0(t) {
    var l = aa(t.target);
    if (l !== null) {
      var e = J(l);
      if (e !== null) {
        if (l = e.tag, l === 13) {
          if (l = M(e), l !== null) {
            t.blockedOn = l, to(t.priority, function() {
              i0(e);
            });
            return;
          }
        } else if (l === 31) {
          if (l = A(e), l !== null) {
            t.blockedOn = l, to(t.priority, function() {
              i0(e);
            });
            return;
          }
        } else if (l === 3 && e.stateNode.current.memoizedState.isDehydrated) {
          t.blockedOn = e.tag === 3 ? e.stateNode.containerInfo : null;
          return;
        }
      }
    }
    t.blockedOn = null;
  }
  function Qi(t) {
    if (t.blockedOn !== null) return !1;
    for (var l = t.targetContainers; 0 < l.length; ) {
      var e = Os(t.nativeEvent);
      if (e === null) {
        e = t.nativeEvent;
        var a = new e.constructor(
          e.type,
          e
        );
        oc = a, e.target.dispatchEvent(a), oc = null;
      } else
        return l = Aa(e), l !== null && n0(l), t.blockedOn = e, !1;
      l.shift();
    }
    return !0;
  }
  function o0(t, l, e) {
    Qi(t) && e.delete(l);
  }
  function Cy() {
    Ms = !1, Fe !== null && Qi(Fe) && (Fe = null), Ie !== null && Qi(Ie) && (Ie = null), Pe !== null && Qi(Pe) && (Pe = null), fn.forEach(o0), sn.forEach(o0);
  }
  function Li(t, l) {
    t.blockedOn === l && (t.blockedOn = null, Ms || (Ms = !0, o.unstable_scheduleCallback(
      o.unstable_NormalPriority,
      Cy
    )));
  }
  var Zi = null;
  function r0(t) {
    Zi !== t && (Zi = t, o.unstable_scheduleCallback(
      o.unstable_NormalPriority,
      function() {
        Zi === t && (Zi = null);
        for (var l = 0; l < t.length; l += 3) {
          var e = t[l], a = t[l + 1], u = t[l + 2];
          if (typeof a != "function") {
            if (As(a || e) === null)
              continue;
            break;
          }
          var n = Aa(e);
          n !== null && (t.splice(l, 3), l -= 3, of(
            n,
            {
              pending: !0,
              data: u,
              method: e.method,
              action: a
            },
            a,
            u
          ));
        }
      }
    ));
  }
  function hu(t) {
    function l(f) {
      return Li(f, t);
    }
    Fe !== null && Li(Fe, t), Ie !== null && Li(Ie, t), Pe !== null && Li(Pe, t), fn.forEach(l), sn.forEach(l);
    for (var e = 0; e < ta.length; e++) {
      var a = ta[e];
      a.blockedOn === t && (a.blockedOn = null);
    }
    for (; 0 < ta.length && (e = ta[0], e.blockedOn === null); )
      s0(e), e.blockedOn === null && ta.shift();
    if (e = (t.ownerDocument || t).$$reactFormReplay, e != null)
      for (a = 0; a < e.length; a += 3) {
        var u = e[a], n = e[a + 1], i = u[vl] || null;
        if (typeof n == "function")
          i || r0(e);
        else if (i) {
          var c = null;
          if (n && n.hasAttribute("formAction")) {
            if (u = n, i = n[vl] || null)
              c = i.formAction;
            else if (As(u) !== null) continue;
          } else c = i.action;
          typeof c == "function" ? e[a + 1] = c : (e.splice(a, 3), a -= 3), r0(e);
        }
      }
  }
  function d0() {
    function t(n) {
      n.canIntercept && n.info === "react-transition" && n.intercept({
        handler: function() {
          return new Promise(function(i) {
            return u = i;
          });
        },
        focusReset: "manual",
        scroll: "manual"
      });
    }
    function l() {
      u !== null && (u(), u = null), a || setTimeout(e, 20);
    }
    function e() {
      if (!a && !navigation.transition) {
        var n = navigation.currentEntry;
        n && n.url != null && navigation.navigate(n.url, {
          state: n.getState(),
          info: "react-transition",
          history: "replace"
        });
      }
    }
    if (typeof navigation == "object") {
      var a = !1, u = null;
      return navigation.addEventListener("navigate", t), navigation.addEventListener("navigatesuccess", l), navigation.addEventListener("navigateerror", l), setTimeout(e, 100), function() {
        a = !0, navigation.removeEventListener("navigate", t), navigation.removeEventListener("navigatesuccess", l), navigation.removeEventListener("navigateerror", l), u !== null && (u(), u = null);
      };
    }
  }
  function Cs(t) {
    this._internalRoot = t;
  }
  wi.prototype.render = Cs.prototype.render = function(t) {
    var l = this._internalRoot;
    if (l === null) throw Error(r(409));
    var e = l.current, a = Ml();
    a0(e, a, t, l, null, null);
  }, wi.prototype.unmount = Cs.prototype.unmount = function() {
    var t = this._internalRoot;
    if (t !== null) {
      this._internalRoot = null;
      var l = t.containerInfo;
      a0(t.current, 2, null, t, null, null), Ai(), l[Oa] = null;
    }
  };
  function wi(t) {
    this._internalRoot = t;
  }
  wi.prototype.unstable_scheduleHydration = function(t) {
    if (t) {
      var l = Ps();
      t = { blockedOn: null, target: t, priority: l };
      for (var e = 0; e < ta.length && l !== 0 && l < ta[e].priority; e++) ;
      ta.splice(e, 0, t), e === 0 && s0(t);
    }
  };
  var m0 = _.version;
  if (m0 !== "19.3.0")
    throw Error(
      r(
        527,
        m0,
        "19.3.0"
      )
    );
  V.findDOMNode = function(t) {
    var l = t._reactInternals;
    if (l === void 0)
      throw typeof t.render == "function" ? Error(r(188)) : (t = Object.keys(t).join(","), Error(r(268, t)));
    return t = L(l), t = t !== null ? R(t) : null, t = t === null ? null : t.stateNode, t;
  };
  var Ry = {
    bundleType: 0,
    version: "19.3.0",
    rendererPackageName: "react-dom",
    currentDispatcherRef: H,
    reconcilerVersion: "19.3.0"
  };
  if (typeof __REACT_DEVTOOLS_GLOBAL_HOOK__ < "u") {
    var Vi = __REACT_DEVTOOLS_GLOBAL_HOOK__;
    if (!Vi.isDisabled && Vi.supportsFiber)
      try {
        gu = Vi.inject(
          Ry
        ), _l = Vi;
      } catch {
      }
  }
  return rn.createRoot = function(t, l) {
    if (!C(t)) throw Error(r(299));
    var e = !1, a = "", u = ed, n = ad, i = ud;
    return l != null && (l.unstable_strictMode === !0 && (e = !0), l.identifierPrefix !== void 0 && (a = l.identifierPrefix), l.onUncaughtError !== void 0 && (u = l.onUncaughtError), l.onCaughtError !== void 0 && (n = l.onCaughtError), l.onRecoverableError !== void 0 && (i = l.onRecoverableError)), l = l0(
      t,
      1,
      !1,
      null,
      null,
      e,
      a,
      null,
      u,
      n,
      i,
      d0
    ), t[Oa] = l.current, is(t), new Cs(l);
  }, rn.hydrateRoot = function(t, l, e) {
    if (!C(t)) throw Error(r(299));
    var a = !1, u = "", n = ed, i = ad, c = ud, f = null;
    return e != null && (e.unstable_strictMode === !0 && (a = !0), e.identifierPrefix !== void 0 && (u = e.identifierPrefix), e.onUncaughtError !== void 0 && (n = e.onUncaughtError), e.onCaughtError !== void 0 && (i = e.onCaughtError), e.onRecoverableError !== void 0 && (c = e.onRecoverableError), e.formState !== void 0 && (f = e.formState)), l = l0(
      t,
      1,
      !0,
      l,
      e ?? null,
      a,
      u,
      f,
      n,
      i,
      c,
      d0
    ), l.context = e0(null), e = l.current, a = Ml(), a = uc(a), u = Ye(a), u.callback = null, Xe(e, u, a), e = a, l.current.lanes = e, Su(l, e), se(l), t[Oa] = l.current, is(t), new wi(l);
  }, rn.version = "19.3.0", rn;
}
var _0;
function Xy() {
  if (_0) return Ds.exports;
  _0 = 1;
  function o() {
    if (!(typeof __REACT_DEVTOOLS_GLOBAL_HOOK__ > "u" || typeof __REACT_DEVTOOLS_GLOBAL_HOOK__.checkDCE != "function"))
      try {
        __REACT_DEVTOOLS_GLOBAL_HOOK__.checkDCE(o);
      } catch (_) {
        console.error(_);
      }
  }
  return o(), Ds.exports = Yy(), Ds.exports;
}
var Gy = Xy();
function Qy(o) {
  const _ = o.indexOf("/api/plugins/");
  return _ >= 0 ? o.slice(0, _) : "";
}
class C0 extends Error {
  constructor(_, E) {
    super(E), this.status = _;
  }
  status;
}
async function R0(o, _) {
  const E = await fetch(o, { credentials: "include", signal: _, headers: { Accept: "application/json" } });
  if (!E.ok) {
    let r = `${E.status}`;
    try {
      const C = await E.json();
      typeof C.detail == "string" && (r = C.detail);
    } catch {
    }
    throw new C0(E.status, r);
  }
  return await E.json();
}
function Ly(o, _, E) {
  return R0(`${o}/api/context-residency/tasks/${encodeURIComponent(_)}`, E);
}
function Zy(o, _, E) {
  return R0(`${o}/api/context-residency/threads/${encodeURIComponent(_)}/tasks`, E);
}
var Bs = { exports: {} }, dn = {};
var T0;
function wy() {
  if (T0) return dn;
  T0 = 1;
  var o = /* @__PURE__ */ Symbol.for("react.transitional.element"), _ = /* @__PURE__ */ Symbol.for("react.fragment");
  function E(r, C, J) {
    var M = null;
    if (J !== void 0 && (M = "" + J), C.key !== void 0 && (M = "" + C.key), "key" in C) {
      J = {};
      for (var A in C)
        A !== "key" && (J[A] = C[A]);
    } else J = C;
    return C = J.ref, {
      $$typeof: o,
      type: r,
      key: M,
      ref: C !== void 0 ? C : null,
      props: J
    };
  }
  return dn.Fragment = _, dn.jsx = E, dn.jsxs = E, dn;
}
var x0;
function Vy() {
  return x0 || (x0 = 1, Bs.exports = wy()), Bs.exports;
}
var m = Vy();
const Ky = (o) => o.replace(/([a-z0-9])([A-Z])/g, "$1-$2").toLowerCase(), Jy = (o) => o.replace(
  /^([A-Z])|[\s-_]+(\w)/g,
  (_, E, r) => r ? r.toUpperCase() : E.toLowerCase()
), E0 = (o) => {
  const _ = Jy(o);
  return _.charAt(0).toUpperCase() + _.slice(1);
}, D0 = (...o) => o.filter((_, E, r) => !!_ && _.trim() !== "" && r.indexOf(_) === E).join(" ").trim(), ky = (o) => {
  for (const _ in o)
    if (_.startsWith("aria-") || _ === "role" || _ === "title")
      return !0;
};
var $y = {
  xmlns: "http://www.w3.org/2000/svg",
  width: 24,
  height: 24,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round",
  strokeLinejoin: "round"
};
const Wy = F.forwardRef(
  ({
    color: o = "currentColor",
    size: _ = 24,
    strokeWidth: E = 2,
    absoluteStrokeWidth: r,
    className: C = "",
    children: J,
    iconNode: M,
    ...A
  }, k) => F.createElement(
    "svg",
    {
      ref: k,
      ...$y,
      width: _,
      height: _,
      stroke: o,
      strokeWidth: r ? Number(E) * 24 / Number(_) : E,
      className: D0("lucide", C),
      ...!J && !ky(A) && { "aria-hidden": "true" },
      ...A
    },
    [
      ...M.map(([L, R]) => F.createElement(L, R)),
      ...Array.isArray(J) ? J : [J]
    ]
  )
);
const U0 = (o, _) => {
  const E = F.forwardRef(
    ({ className: r, ...C }, J) => F.createElement(Wy, {
      ref: J,
      iconNode: _,
      className: D0(
        `lucide-${Ky(E0(o))}`,
        `lucide-${o}`,
        r
      ),
      ...C
    })
  );
  return E.displayName = E0(o), E;
};
const Fy = [
  ["path", { d: "M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8", key: "v9h5vc" }],
  ["path", { d: "M21 3v5h-5", key: "1q7to0" }],
  ["path", { d: "M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16", key: "3uifl3" }],
  ["path", { d: "M8 16H3v5", key: "1cv678" }]
], Iy = U0("refresh-cw", Fy);
const Py = [
  ["circle", { cx: "6", cy: "6", r: "3", key: "1lh9wr" }],
  ["path", { d: "M8.12 8.12 12 12", key: "1alkpv" }],
  ["path", { d: "M20 4 8.12 15.88", key: "xgtan2" }],
  ["circle", { cx: "6", cy: "18", r: "3", key: "fqmcym" }],
  ["path", { d: "M14.8 14.8 20 20", key: "ptml3r" }]
], j0 = U0("scissors", Py), t1 = {
  title: "Context residency",
  empty: "No recorded model requests for this task.",
  attemptsTruncated: "Attempt list truncated at the server cap — the earliest attempts are shown.",
  coverage: "Presence is derived from recorded request inventories only. Absence inside an incomplete inventory renders as unknown — never as removal — and removal causes come only from recorded compaction memberships.",
  refresh: "Refresh",
  hint: "⌘/Ctrl+wheel zoom · drag the minimap to zoom, click to reset · ←/→ attempt",
  laneSystem: "System prompt",
  laneToolSchema: "Tool schema",
  laneMemory: "Memory",
  laneSkill: "Skill",
  laneUser: "User input",
  laneAssistant: "Assistant",
  laneToolResult: "Tool result",
  laneSummary: "Summary",
  laneMiddleware: "Middleware injection",
  laneAttachment: "Attachment",
  laneUnknown: "Unknown",
  lowerBound: "lower bound",
  composition: "Composition",
  compression: "Compaction",
  snapshot: "Request",
  retryAttempt: "retry attempt",
  total: "Total",
  members: "Ordered members",
  sortContext: "Context order",
  sortShare: "By share",
  memberUnprojected: "block not recorded",
  incompleteNote: "This inventory is incomplete: members that could not be serialized are missing, so the total is a lower bound and absences here are unknown, not removals.",
  unanchored: "Not positioned on the attempt stream",
  block: "Block",
  residence: "Residence",
  firstSeen: "First seen",
  lastSeen: "Last seen",
  removedBy: "Removed by",
  continuesIn: "continues in",
  removalUnrecorded: "no recorded removal cause",
  stillPresent: "Present in the latest recorded request.",
  preservedBy: "Preserved by",
  summaryOf: "Summary of",
  positionedBefore: "positioned before",
  compressionScope: "Request totals across the boundary",
  removed: "Removed",
  preserved: "Preserved",
  summaryBlock: "Summary carrier",
  summaryBlockUnknown: "No later request declared this summary.",
  loading: "Loading…",
  loadFailed: "Could not load the recording.",
  tasks: "Recorded tasks",
  noTasks: "No recorded tasks for this conversation.",
  threadLabel: "Conversation id",
  taskLabel: "Task id",
  load: "Load",
  taskKindLead: "lead",
  taskKindSubagent: "subagent",
  recordingOff: "The extension is not recording (no database, or disabled).",
  dropped: (o) => `${o} event(s) were dropped by the recorder; some inventories may be missing.`
}, l1 = {
  title: "上下文留存",
  empty: "该任务没有记录到模型请求。",
  attemptsTruncated: "attempt 列表已在服务端上限截断——展示最早的 attempts。",
  coverage: "存在性仅由已记录的请求成员清单推导。不完整清单中的缺席渲染为未知——从不作移出断言——移出原因只来自已记录的压缩成员关系。",
  refresh: "刷新",
  hint: "⌘/Ctrl+滚轮 缩放 · minimap 拖拽圈选 / 单击复位 · ←/→ 切换 attempt",
  laneSystem: "系统提示",
  laneToolSchema: "工具 Schema",
  laneMemory: "Memory 注入",
  laneSkill: "Skill 注入",
  laneUser: "用户输入",
  laneAssistant: "助手消息",
  laneToolResult: "工具结果",
  laneSummary: "压缩摘要",
  laneMiddleware: "Middleware 注入",
  laneAttachment: "附件",
  laneUnknown: "未知",
  lowerBound: "下界",
  composition: "组成占比",
  compression: "压缩",
  snapshot: "请求",
  retryAttempt: "重试 attempt",
  total: "合计",
  members: "有序成员",
  sortContext: "上下文顺序",
  sortShare: "按占比",
  memberUnprojected: "块未记录",
  incompleteNote: "这份清单不完整：无法序列化的成员缺失，合计只是下界，这里的缺席是未知而不是移出。",
  unanchored: "未定位到 attempt 流",
  block: "块",
  residence: "留存",
  firstSeen: "首见",
  lastSeen: "末见",
  removedBy: "移出于",
  continuesIn: "延续为",
  removalUnrecorded: "移出原因未记录",
  stillPresent: "仍在最新记录的请求中。",
  preservedBy: "被保留于",
  summaryOf: "摘要自",
  positionedBefore: "定位在",
  compressionScope: "边界两侧的请求合计",
  removed: "移出",
  preserved: "保留",
  summaryBlock: "摘要承载块",
  summaryBlockUnknown: "之后的请求没有声明这条摘要。",
  loading: "加载中…",
  loadFailed: "无法加载记录。",
  tasks: "已记录的任务",
  noTasks: "该会话没有记录到任务。",
  threadLabel: "会话 id",
  taskLabel: "任务 id",
  load: "加载",
  taskKindLead: "主代理",
  taskKindSubagent: "子代理",
  recordingOff: "扩展未在记录（没有数据库，或已禁用）。",
  dropped: (o) => `记录器丢弃了 ${o} 个事件；部分清单可能缺失。`
};
function e1(o) {
  return o?.toLowerCase().startsWith("zh") ? l1 : t1;
}
function ki(o, _) {
  if (!o) return "—";
  const E = new Date(o);
  return Number.isNaN(E.getTime()) ? o : new Intl.DateTimeFormat(_?.toLowerCase().startsWith("zh") ? "zh-CN" : "en-US", {
    dateStyle: "medium",
    timeStyle: "medium"
  }).format(E);
}
function Ll(o, _ = 8) {
  return o.length <= _ ? o : o.slice(0, _);
}
const mn = [
  "system",
  "tool_schema",
  "memory",
  "skill",
  "user",
  "assistant",
  "tool_result",
  "summary",
  "middleware",
  "attachment",
  "unknown"
];
function H0(o) {
  if (o === null) return "unknown";
  if (o.channel === "tool_schema") return "tool_schema";
  switch (o.kind) {
    case "system_prompt":
      return "system";
    case "tool_schema":
      return "tool_schema";
    case "memory":
      return "memory";
    case "skill_instruction":
      return "skill";
    case "user_input":
      return "user";
    case "assistant_output":
    case "assistant_reasoning":
    case "tool_request":
      return "assistant";
    case "tool_result_raw":
    case "tool_result_visible":
      return "tool_result";
    case "summary":
      return "summary";
    case "middleware_injection":
    case "durable_context":
      return "middleware";
    case "image_or_attachment":
      return "attachment";
    default:
      return "unknown";
  }
}
function a1(o) {
  const _ = o.attempts, E = _.map(
    (X) => new Map(X.members.map((G) => [G.block_id, G]))
  ), r = [], C = /* @__PURE__ */ new Set();
  for (const X of _)
    for (const G of X.members)
      C.has(G.block_id) || (C.add(G.block_id), r.push(G.block_id));
  const J = /* @__PURE__ */ new Map(), M = /* @__PURE__ */ new Map(), A = /* @__PURE__ */ new Map();
  for (const X of o.compressions) {
    for (const G of X.removed_block_ids)
      J.has(G) || J.set(G, X.compression_id);
    for (const G of X.preserved_block_ids) {
      const q = M.get(G) ?? [];
      q.push(X.compression_id), M.set(G, q);
    }
    X.summary_block_id !== null && !A.has(X.summary_block_id) && A.set(X.summary_block_id, X.compression_id);
  }
  const k = r.map((X) => {
    const G = o.blocks[X] ?? null, q = [], at = [], Ot = [];
    let ht = -1, Pt = -1, St = 0, Mt = 0, pt = 0;
    return _.forEach((ut, lt) => {
      const Ht = E[lt].get(X);
      if (Ht !== void 0) {
        q.push("present"), St += 1, Mt = Ht.estimated_tokens, pt = Ht.visible_bytes, ht === -1 && (ht = lt), Pt = lt;
        const $ = at[at.length - 1];
        $?.end === lt - 1 ? $.end = lt : at.push({ start: lt, end: lt });
      } else ut.status === "incomplete" ? (q.push("unknown"), Ot.push(lt)) : q.push("absent");
    }), {
      blockId: X,
      meta: G,
      lane: H0(G),
      presence: q,
      runs: at,
      unknownAt: Ot,
      firstSeen: ht,
      lastSeen: Pt,
      presentCount: St,
      sizeTokens: Mt,
      sizeBytes: pt,
      removedBy: J.get(X) ?? null,
      preservedBy: M.get(X) ?? [],
      summaryOf: A.get(X) ?? null
    };
  }), L = /* @__PURE__ */ new Map();
  for (const X of k) {
    const G = L.get(X.lane) ?? [];
    G.push(X), L.set(X.lane, G);
  }
  const R = mn.filter((X) => L.has(X)).map(
    (X) => ({ lane: X, rows: L.get(X) })
  ), p = /* @__PURE__ */ new Map(), U = [];
  for (const X of o.compressions) {
    const G = X.positioned_before_attempt_id;
    if (G !== null && _.some((q) => q.attempt_id === G)) {
      const q = p.get(G) ?? [];
      q.push(X), p.set(G, q);
    } else
      U.push(X);
  }
  return {
    attempts: _,
    rows: k,
    lanes: R,
    compressions: o.compressions,
    compressionsBefore: p,
    unanchoredCompressions: U,
    attemptsTruncated: o.attempts_truncated
  };
}
function Na(o, _) {
  return _ === "tokens" ? o.estimated_tokens : o.visible_bytes;
}
function u1(o, _, E) {
  return _ === "context" ? o : [...o].sort(
    (r, C) => Na(C, E) - Na(r, E)
  );
}
function Ki(o, _) {
  return _ === "tokens" ? o.estimated_tokens : o.visible_bytes;
}
function Gs(o, _, E) {
  const r = /* @__PURE__ */ new Map();
  for (const C of o.members) {
    const J = H0(_[C.block_id] ?? null);
    r.set(J, (r.get(J) ?? 0) + Na(C, E));
  }
  return mn.filter((C) => r.has(C)).map((C) => ({
    lane: C,
    size: r.get(C)
  }));
}
function B0(o) {
  var _, E, r = "";
  if (typeof o == "string" || typeof o == "number") r += o;
  else if (typeof o == "object") if (Array.isArray(o)) {
    var C = o.length;
    for (_ = 0; _ < C; _++) o[_] && (E = B0(o[_])) && (r && (r += " "), r += E);
  } else for (E in o) o[E] && (r && (r += " "), r += E);
  return r;
}
function n1() {
  for (var o, _, E = 0, r = "", C = arguments.length; E < C; E++) (o = arguments[E]) && (_ = B0(o)) && (r && (r += " "), r += _);
  return r;
}
function Jt(...o) {
  return n1(o);
}
const i1 = {
  secondary: "bg-secondary text-secondary-foreground hover:bg-secondary/80",
  ghost: "hover:bg-muted",
  outline: "border bg-background hover:bg-muted"
};
function vn({ variant: o = "outline", size: _, className: E, type: r = "button", ...C }) {
  return /* @__PURE__ */ m.jsx(
    "button",
    {
      type: r,
      className: Jt(
        "inline-flex items-center justify-center gap-1.5 rounded-md text-sm font-medium whitespace-nowrap transition-colors disabled:pointer-events-none disabled:opacity-50",
        _ === "sm" ? "h-8 px-3 text-xs" : "h-9 px-4",
        i1[o],
        E
      ),
      ...C
    }
  );
}
function Ji({ className: o, ..._ }) {
  return /* @__PURE__ */ m.jsx("span", { className: Jt("inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium", o), ..._ });
}
function N0({ className: o, ..._ }) {
  return /* @__PURE__ */ m.jsx("div", { className: Jt("bg-muted animate-pulse rounded-md", o), ..._ });
}
const qs = 96, c1 = 56, Ys = 4, Fl = {
  system: "bg-indigo-500/75",
  tool_schema: "bg-slate-400/60",
  memory: "bg-violet-500/75",
  skill: "bg-teal-500/75",
  user: "bg-sky-500/75",
  assistant: "bg-blue-500/75",
  tool_result: "bg-cyan-500/70",
  summary: "bg-purple-500/75",
  middleware: "bg-slate-500/70",
  attachment: "bg-slate-400/50",
  unknown: "bg-muted-foreground/30"
}, z0 = {
  system: "#6366f1",
  tool_schema: "#94a3b8",
  memory: "#8b5cf6",
  skill: "#14b8a6",
  user: "#0ea5e9",
  assistant: "#3b82f6",
  tool_result: "#06b6d4",
  summary: "#a855f7",
  middleware: "#64748b",
  attachment: "#94a3b8",
  unknown: "#94a3b8"
}, O0 = "bg-[repeating-linear-gradient(135deg,transparent_0_4px,var(--color-border)_4px_6px)]";
function ze(o, _) {
  return _ === "tokens" ? o >= 1e3 ? `${(o / 1e3).toFixed(1)}k` : String(o) : o >= 1024 ? `${(o / 1024).toFixed(1)} KB` : `${o} B`;
}
function Xs(o, _) {
  return _ <= 0 ? "—" : `${(o / _ * 100).toFixed(1)}%`;
}
function Rl(o) {
  const _ = `S${o.step_seq}`;
  return o.attempt_no > 1 ? `${_}·a${o.attempt_no}` : _;
}
function hn(o, _) {
  switch (_) {
    case "system":
      return o.laneSystem;
    case "tool_schema":
      return o.laneToolSchema;
    case "memory":
      return o.laneMemory;
    case "skill":
      return o.laneSkill;
    case "user":
      return o.laneUser;
    case "assistant":
      return o.laneAssistant;
    case "tool_result":
      return o.laneToolResult;
    case "summary":
      return o.laneSummary;
    case "middleware":
      return o.laneMiddleware;
    case "attachment":
      return o.laneAttachment;
    case "unknown":
      return o.laneUnknown;
  }
}
function $i(o, _) {
  return _.meta?.name ? _.meta.name : _.meta?.kind ? _.meta.kind : `${o.block} ${Ll(_.blockId)}`;
}
function f1({
  response: o,
  locale: _,
  t: E,
  onRefresh: r,
  refreshing: C,
  seedStepSeq: J
}) {
  const M = F.useMemo(() => a1(o), [o]), [A, k] = F.useState("tokens"), [L, R] = F.useState(() => {
    if (J != null) {
      const x = M.attempts.findIndex((O) => O.step_seq === J && O.effective), s = M.attempts.findIndex((O) => O.step_seq === J), T = x >= 0 ? x : s;
      if (T >= 0) return T;
    }
    return M.attempts.length > 0 ? M.attempts.length - 1 : null;
  }), [p, U] = F.useState({ mode: "attempt" }), [X, G] = F.useState(() => new Set(mn)), q = M.attempts.length, at = F.useMemo(
    () => Math.max(1, ...M.attempts.map((x) => Ki(x, A))),
    [M.attempts, A]
  ), Ot = F.useMemo(
    () => M.attempts.flatMap((x, s) => M.compressionsBefore.has(x.attempt_id) ? [s] : []),
    [M]
  ), ht = F.useRef(null), Pt = F.useRef(null), St = F.useRef(24), Mt = F.useRef(Ys), pt = F.useRef(0), ut = F.useCallback(() => {
    const x = Pt.current;
    if (!x) return;
    const s = St.current;
    x.dataset.density = s < 16 ? "dense" : s < 34 ? "mid" : "full";
    const T = s >= 34 ? 1 : Math.max(1, Math.ceil(38 / s));
    x.querySelectorAll("[data-attempt-header]").forEach((O, D) => {
      O.dataset.lbl = D % T === 0 ? "on" : "off";
    });
  }, []), lt = F.useRef(null), Ht = F.useRef(null), $ = F.useRef(null), _t = F.useRef(null), gt = F.useRef(null), qt = F.useCallback(() => {
    const x = ht.current, s = lt.current, T = $.current;
    if (!x || !s || q === 0 || gt.current?.mode === "select") return;
    const O = St.current, D = pt.current, Y = Math.max(0, x.scrollLeft / O), w = Math.min(q, (x.scrollLeft + x.clientWidth - D) / O);
    if (s.style.left = `${Y / q * 100}%`, s.style.width = `${Math.max(0.4, w - Y) / q * 100}%`, T) {
      const I = M.attempts[Math.min(q - 1, Math.floor(Y))], H = M.attempts[Math.min(q - 1, Math.max(0, Math.ceil(w) - 1))];
      I && H && (T.textContent = `${Rl(I)} – ${Rl(H)} · ${Math.round(w - Y)}/${q}`);
    }
  }, [q, M.attempts]), cl = F.useCallback(
    (x, s, T) => {
      const O = ht.current, D = Pt.current;
      if (!O || !D) return;
      const Y = Math.max(Mt.current, Math.min(c1, x));
      St.current = Y, D.style.setProperty("--residency-colw", `${Y}px`), s !== void 0 && T !== void 0 && (O.scrollLeft = Math.max(0, pt.current + s * Y - T)), ut(), qt();
    },
    [qt, ut]
  ), Yt = F.useCallback(() => {
    const x = ht.current;
    return !x || q === 0 ? Ys : Math.max(Ys, Math.floor((x.clientWidth - pt.current) / q));
  }, [q]);
  F.useEffect(() => {
    const x = ht.current, s = Pt.current;
    if (!x || !s || q === 0) return;
    const T = s.querySelector("[data-residency-label]");
    pt.current = T?.offsetWidth ?? 0, Mt.current = Yt(), cl(Mt.current), x.scrollLeft = 0;
    const O = new ResizeObserver(() => {
      const D = St.current <= Mt.current + 0.5;
      Mt.current = Yt(), (D || St.current < Mt.current) && cl(Mt.current), qt();
    });
    return O.observe(x), () => O.disconnect();
  }, [q, Yt, cl, qt]), F.useEffect(() => {
    const x = ht.current;
    if (!x) return;
    const s = (O) => {
      if (!(O.ctrlKey || O.metaKey)) return;
      O.preventDefault();
      const D = x.getBoundingClientRect(), Y = O.clientX - D.left, w = (x.scrollLeft + Y - pt.current) / St.current;
      cl(St.current * Math.exp(-O.deltaY * 25e-4), w, Y);
    }, T = () => requestAnimationFrame(qt);
    return x.addEventListener("wheel", s, { passive: !1 }), x.addEventListener("scroll", T), () => {
      x.removeEventListener("wheel", s), x.removeEventListener("scroll", T);
    };
  }, [cl, qt]);
  const B = F.useRef(null);
  F.useEffect(() => {
    const x = B.current, s = _t.current;
    if (!x || !s || q === 0) return;
    const T = s.clientWidth, O = s.clientHeight, D = window.devicePixelRatio || 1;
    x.width = T * D, x.height = O * D;
    const Y = x.getContext("2d");
    if (!Y) return;
    Y.setTransform(D, 0, 0, D, 0, 0), Y.clearRect(0, 0, T, O);
    const w = T / q, I = 3, H = O - I * 2;
    M.attempts.forEach((V, Ut) => {
      let oe = O - I;
      for (const { lane: wl, size: Dl } of Gs(V, o.blocks, A)) {
        const Qt = Math.max(0.5, Dl / at * H);
        Y.fillStyle = z0[wl], Y.globalAlpha = X.has(wl) ? 0.8 : 0.15, Y.fillRect(Ut * w, oe - Qt, Math.max(1, w - 0.4), Qt), oe -= Qt;
      }
      Y.globalAlpha = 1, V.status === "incomplete" && (Y.fillStyle = "#d97706", Y.fillRect(Ut * w, 0, Math.max(1.5, w - 0.4), 2.5));
    }), Y.strokeStyle = z0.summary, Y.setLineDash([3, 3]), Y.lineWidth = 1.5;
    for (const V of Ot) {
      const Ut = V * w;
      Y.beginPath(), Y.moveTo(Ut, 0), Y.lineTo(Ut, O), Y.stroke();
    }
    Y.setLineDash([]), qt();
  }, [X, q, Ot, at, A, M, o.blocks, qt]), F.useEffect(() => {
    const x = _t.current, s = lt.current, T = ht.current;
    if (!x || !s || !T || q === 0) return;
    const O = (w) => {
      const I = x.getBoundingClientRect(), H = w.clientX - I.left, V = s.getBoundingClientRect(), Ut = w.clientX >= V.left && w.clientX <= V.right, wl = (T.clientWidth - pt.current) / St.current >= q - 0.5;
      x.setPointerCapture(w.pointerId), Ut && !wl ? gt.current = { mode: "pan", startX: H, startScroll: T.scrollLeft } : gt.current = { mode: "select", anchorX: H, lastX: H };
    }, D = (w) => {
      const I = gt.current;
      if (!I) return;
      const H = x.getBoundingClientRect(), V = Math.max(0, Math.min(H.width, w.clientX - H.left));
      if (I.mode === "pan") {
        const Ut = (V - I.startX) / H.width * q;
        T.scrollLeft = I.startScroll + Ut * St.current;
      } else {
        I.lastX = V;
        const Ut = Math.min(I.anchorX, V), oe = Math.max(I.anchorX, V);
        s.style.left = `${Ut / H.width * 100}%`, s.style.width = `${Math.max(2, oe - Ut) / H.width * 100}%`;
      }
    }, Y = () => {
      const w = gt.current;
      if (gt.current = null, w?.mode !== "select") {
        qt();
        return;
      }
      const I = x.getBoundingClientRect();
      if (Math.abs(w.lastX - w.anchorX) < 3) {
        cl(Mt.current), T.scrollLeft = 0;
        return;
      }
      const H = Math.max(0, Math.min(w.anchorX, w.lastX) / I.width * q), V = Math.min(q, Math.max(w.anchorX, w.lastX) / I.width * q), Ut = Math.max(2, V - H);
      cl((T.clientWidth - pt.current) / Ut), T.scrollLeft = H * St.current, qt();
    };
    return x.addEventListener("pointerdown", O), x.addEventListener("pointermove", D), x.addEventListener("pointerup", Y), () => {
      x.removeEventListener("pointerdown", O), x.removeEventListener("pointermove", D), x.removeEventListener("pointerup", Y);
    };
  }, [q, cl, qt]), F.useEffect(() => {
    const x = Ht.current;
    if (!(!x || q === 0)) {
      if (L === null) {
        x.style.display = "none";
        return;
      }
      x.style.display = "block", x.style.left = `${(L + 0.5) / q * 100}%`;
    }
  }, [q, L]);
  const W = F.useCallback((x, s = !1) => {
    R(x), s || U({ mode: "attempt" });
    const T = ht.current;
    if (!T) return;
    const O = St.current, D = pt.current, Y = D + x * O;
    Y - T.scrollLeft < D ? T.scrollLeft = x * O : Y + O - T.scrollLeft > T.clientWidth && (T.scrollLeft = Y + O - T.clientWidth);
  }, []), tt = F.useCallback(
    (x) => {
      if (x.key === "Escape") {
        U({ mode: "attempt" });
        return;
      }
      if (x.key !== "ArrowLeft" && x.key !== "ArrowRight" || L === null || q === 0) return;
      const s = L + (x.key === "ArrowRight" ? 1 : -1);
      s < 0 || s >= q || (x.preventDefault(), W(s));
    },
    [q, W, L]
  ), Tt = F.useCallback((x) => {
    G((s) => {
      const T = mn;
      if (s.size === T.length) return /* @__PURE__ */ new Set([x]);
      const O = new Set(s);
      if (O.has(x)) {
        if (O.delete(x), O.size === 0) return new Set(T);
      } else if (O.add(x), O.size === T.length) return new Set(T);
      return O;
    });
  }, []), dt = X.size < mn.length, sl = F.useCallback((x) => dt && !X.has(x), [X, dt]), Zl = F.useMemo(() => M.lanes.map((x) => x.lane), [M.lanes]);
  return q === 0 ? /* @__PURE__ */ m.jsxs("div", { className: "space-y-2", "data-residency-empty": !0, children: [
    /* @__PURE__ */ m.jsx("p", { className: "text-muted-foreground text-sm", children: E.empty }),
    M.attemptsTruncated ? /* @__PURE__ */ m.jsx("p", { className: "text-xs text-amber-600", children: E.attemptsTruncated }) : null
  ] }) : /* @__PURE__ */ m.jsxs("div", { className: "space-y-3", "data-residency-board": !0, children: [
    /* @__PURE__ */ m.jsxs("div", { className: "flex flex-wrap items-start justify-between gap-x-6 gap-y-2", children: [
      /* @__PURE__ */ m.jsx("p", { className: "text-muted-foreground max-w-3xl text-xs", children: E.coverage }),
      /* @__PURE__ */ m.jsxs("div", { className: "flex shrink-0 items-center gap-2", children: [
        /* @__PURE__ */ m.jsx("div", { className: "flex items-center gap-1 rounded-md border p-0.5", children: ["tokens", "bytes"].map((x) => /* @__PURE__ */ m.jsx(
          vn,
          {
            size: "sm",
            variant: A === x ? "secondary" : "ghost",
            className: "h-6 px-2 text-xs",
            "aria-pressed": A === x,
            onClick: () => k(x),
            children: x
          },
          x
        )) }),
        /* @__PURE__ */ m.jsxs(vn, { size: "sm", variant: "ghost", className: "h-7 px-2 text-xs", onClick: r, disabled: C, children: [
          /* @__PURE__ */ m.jsx(Iy, { className: Jt("size-3.5", C && "animate-spin") }),
          E.refresh
        ] })
      ] })
    ] }),
    M.attemptsTruncated ? /* @__PURE__ */ m.jsx("p", { className: "text-xs text-amber-600", children: E.attemptsTruncated }) : null,
    /* @__PURE__ */ m.jsxs("div", { className: "flex flex-wrap items-center gap-1.5", children: [
      Zl.map((x) => /* @__PURE__ */ m.jsxs(
        "button",
        {
          type: "button",
          "aria-pressed": !dt || X.has(x),
          onClick: () => Tt(x),
          className: Jt(
            "focus-visible:ring-ring inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs transition-colors focus-visible:ring-2 focus-visible:outline-none",
            sl(x) && "opacity-35"
          ),
          children: [
            /* @__PURE__ */ m.jsx("span", { className: Jt("size-2 rounded-[3px]", Fl[x]) }),
            hn(E, x)
          ]
        },
        x
      )),
      /* @__PURE__ */ m.jsx("span", { className: "text-muted-foreground/70 ml-auto hidden text-[11px] lg:inline", children: E.hint })
    ] }),
    /* @__PURE__ */ m.jsxs("div", { className: "grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]", children: [
      /* @__PURE__ */ m.jsxs("div", { className: "min-w-0 rounded-md border", tabIndex: 0, onKeyDown: tt, "aria-label": E.title, children: [
        /* @__PURE__ */ m.jsxs("div", { ref: _t, className: "relative h-12 cursor-crosshair touch-none overflow-hidden border-b select-none", children: [
          /* @__PURE__ */ m.jsx("canvas", { ref: B, className: "block h-full w-full" }),
          /* @__PURE__ */ m.jsx("div", { ref: lt, className: "border-primary bg-primary/10 absolute inset-y-0 cursor-grab border-x" }),
          /* @__PURE__ */ m.jsx("div", { ref: Ht, className: "bg-primary/70 pointer-events-none absolute inset-y-0 w-0.5" }),
          /* @__PURE__ */ m.jsx(
            "div",
            {
              ref: $,
              className: "text-muted-foreground bg-background/70 pointer-events-none absolute top-1 right-2 rounded px-1 font-mono text-[10px]"
            }
          )
        ] }),
        /* @__PURE__ */ m.jsx("div", { ref: ht, className: "overflow-x-auto", children: /* @__PURE__ */ m.jsxs(
          "div",
          {
            ref: Pt,
            className: "group/board relative isolate min-w-max",
            style: { "--residency-colw": "24px" },
            "data-density": "mid",
            children: [
              /* @__PURE__ */ m.jsx("div", { "aria-hidden": !0, className: "pointer-events-none absolute inset-y-0 left-44 -z-10", children: Ot.map((x) => /* @__PURE__ */ m.jsx(
                "span",
                {
                  "data-residency-boundary": x,
                  className: "absolute inset-y-0 w-0 border-l-2 border-dashed border-purple-500/50",
                  style: { left: `calc(${x} * var(--residency-colw))` }
                },
                M.attempts[x].attempt_id
              )) }),
              /* @__PURE__ */ m.jsxs("div", { className: "flex border-b", children: [
                /* @__PURE__ */ m.jsx(
                  "div",
                  {
                    "data-residency-label": !0,
                    className: "bg-card text-muted-foreground sticky left-0 z-[5] w-44 shrink-0 border-r px-3 py-1 text-[11px]",
                    children: "attempt →"
                  }
                ),
                M.attempts.map((x, s) => {
                  const T = M.compressionsBefore.get(x.attempt_id) ?? [], O = () => U({ mode: "compression", compressionId: T[0].compression_id });
                  return /* @__PURE__ */ m.jsxs(
                    "button",
                    {
                      type: "button",
                      "data-attempt-header": !0,
                      "data-lbl": "on",
                      onClick: () => W(s),
                      title: `${Rl(x)}${x.occurred_at ? ` · ${ki(x.occurred_at, _)}` : ""} · ${ze(Ki(x, A), A)}${x.status === "incomplete" ? ` (${E.lowerBound})` : ""}`,
                      className: Jt(
                        "group/hcell relative w-(--residency-colw) shrink-0 overflow-visible py-1 text-center",
                        x.status === "incomplete" && O0,
                        L === s && "bg-primary/10 shadow-[inset_0_-2px_0_var(--color-primary)]"
                      ),
                      children: [
                        T.length > 0 ? /* @__PURE__ */ m.jsxs(
                          "span",
                          {
                            role: "button",
                            tabIndex: 0,
                            "data-residency-compression-marker": !0,
                            onClick: (D) => {
                              D.stopPropagation(), O();
                            },
                            onKeyDown: (D) => {
                              (D.key === "Enter" || D.key === " ") && (D.stopPropagation(), O());
                            },
                            title: E.compression,
                            className: "bg-card absolute -top-0.5 left-0 z-[5] inline-flex -translate-x-1/2 items-center gap-0.5 rounded-full border border-purple-500/60 px-1 text-[9px] leading-4 text-purple-600",
                            children: [
                              /* @__PURE__ */ m.jsx(j0, { className: "size-2.5" }),
                              T.length > 1 ? `×${T.length}` : null
                            ]
                          }
                        ) : null,
                        /* @__PURE__ */ m.jsx(
                          "span",
                          {
                            className: Jt(
                              "text-foreground text-[11px] font-medium whitespace-nowrap",
                              L === s ? "text-primary" : "group-data-[lbl=off]/hcell:invisible"
                            ),
                            children: Rl(x)
                          }
                        ),
                        x.status === "incomplete" ? /* @__PURE__ */ m.jsx("span", { className: "absolute top-0.5 right-0.5 size-1.5 rounded-full bg-amber-500" }) : null
                      ]
                    },
                    x.attempt_id
                  );
                })
              ] }),
              /* @__PURE__ */ m.jsxs("div", { className: "flex border-b", children: [
                /* @__PURE__ */ m.jsx("div", { className: "bg-card sticky left-0 z-[5] flex w-44 shrink-0 items-end border-r px-3 py-1", children: /* @__PURE__ */ m.jsxs("div", { className: "text-muted-foreground text-[11px] leading-tight", children: [
                  /* @__PURE__ */ m.jsx("div", { className: "text-foreground/80 font-medium", children: E.composition }),
                  /* @__PURE__ */ m.jsx("div", { children: A })
                ] }) }),
                M.attempts.map((x, s) => {
                  const T = Ki(x, A), O = Gs(x, o.blocks, A), D = M.compressionsBefore.has(x.attempt_id);
                  return /* @__PURE__ */ m.jsx(
                    "button",
                    {
                      type: "button",
                      onClick: () => W(s),
                      title: `${Rl(x)} · ${ze(T, A)} ${A}${x.status === "incomplete" ? ` (${E.lowerBound})` : ""}`,
                      className: Jt(
                        "flex w-(--residency-colw) shrink-0 items-end justify-center px-px pt-1.5 group-data-[density=full]/board:px-1",
                        D && "border-l-2 border-transparent",
                        x.status === "incomplete" && O0,
                        L === s && "bg-primary/10"
                      ),
                      style: { height: qs + 8 },
                      children: /* @__PURE__ */ m.jsxs(
                        "span",
                        {
                          className: "flex w-full flex-col justify-end overflow-hidden rounded-t-[2px]",
                          style: { height: Math.max(4, Math.round(T / at * qs)) },
                          children: [
                            x.status === "incomplete" ? /* @__PURE__ */ m.jsx("span", { className: "h-2 w-full border border-b-0 border-dashed border-amber-500/50 bg-[repeating-linear-gradient(135deg,transparent_0_3px,var(--color-border)_3px_5px)]" }) : null,
                            O.map(({ lane: Y, size: w }) => /* @__PURE__ */ m.jsx(
                              "span",
                              {
                                className: Jt("w-full", Fl[Y], sl(Y) && "opacity-20"),
                                style: { height: Math.max(2, Math.round(w / at * qs)) }
                              },
                              Y
                            ))
                          ]
                        }
                      )
                    },
                    x.attempt_id
                  );
                })
              ] }),
              M.lanes.map((x) => /* @__PURE__ */ m.jsxs("div", { className: Jt(sl(x.lane) && "opacity-35"), children: [
                /* @__PURE__ */ m.jsx("div", { className: "bg-muted/50 border-b", children: /* @__PURE__ */ m.jsxs("div", { className: "bg-muted/50 sticky left-0 z-[5] inline-flex items-center gap-1.5 px-3 py-0.5 text-[10px] font-semibold tracking-wide uppercase", children: [
                  /* @__PURE__ */ m.jsx("span", { className: Jt("size-1.5 rounded-[2px]", Fl[x.lane]) }),
                  hn(E, x.lane),
                  /* @__PURE__ */ m.jsxs("span", { className: "text-muted-foreground font-normal", children: [
                    "· ",
                    x.rows.length
                  ] })
                ] }) }),
                x.rows.map((s) => /* @__PURE__ */ m.jsx(
                  s1,
                  {
                    row: s,
                    model: M,
                    measure: A,
                    selectedAttempt: L,
                    onSelectBlock: (T, O) => {
                      O !== null && W(O, !0), U({ mode: "block", blockId: T });
                    },
                    colwRef: St,
                    title: $i(E, s)
                  },
                  s.blockId
                ))
              ] }, x.lane))
            ]
          }
        ) })
      ] }),
      /* @__PURE__ */ m.jsx(
        o1,
        {
          model: M,
          response: o,
          measure: A,
          selectedAttempt: L,
          panel: p,
          locale: _,
          t: E,
          onSelectAttempt: (x) => W(x),
          onSelectBlock: (x) => U({ mode: "block", blockId: x }),
          onSelectCompression: (x) => U({ mode: "compression", compressionId: x })
        }
      )
    ] })
  ] });
}
function s1({
  row: o,
  model: _,
  measure: E,
  selectedAttempt: r,
  onSelectBlock: C,
  colwRef: J,
  title: M
}) {
  const A = _.attempts.length;
  return /* @__PURE__ */ m.jsxs("div", { className: "border-border/50 flex h-7 items-stretch border-b", "data-residency-row": o.blockId, children: [
    /* @__PURE__ */ m.jsxs(
      "button",
      {
        type: "button",
        onClick: () => C(o.blockId, null),
        className: "bg-card hover:bg-muted/60 sticky left-0 z-[5] flex w-44 shrink-0 items-center gap-1.5 truncate border-r px-3 text-left text-xs",
        title: M,
        children: [
          /* @__PURE__ */ m.jsx("span", { className: Jt("size-2 shrink-0 rounded-[3px]", Fl[o.lane]) }),
          /* @__PURE__ */ m.jsx("span", { className: "truncate", children: M }),
          /* @__PURE__ */ m.jsx("span", { className: "text-muted-foreground/70 ml-auto shrink-0 font-mono text-[10px]", children: ze(Na({ estimated_tokens: o.sizeTokens, visible_bytes: o.sizeBytes }, E), E) })
        ]
      }
    ),
    /* @__PURE__ */ m.jsxs("div", { className: "relative grid items-center", style: { gridTemplateColumns: `repeat(${A}, var(--residency-colw))` }, children: [
      r !== null ? /* @__PURE__ */ m.jsx(
        "span",
        {
          className: "bg-primary/8 pointer-events-none absolute inset-y-0",
          style: { left: `calc(${r} * var(--residency-colw))`, width: "var(--residency-colw)" }
        }
      ) : null,
      o.runs.map((k) => /* @__PURE__ */ m.jsx(
        "button",
        {
          type: "button",
          "data-residency-run": !0,
          onClick: (L) => {
            const R = L.currentTarget.getBoundingClientRect(), p = Math.floor((L.clientX - R.left) / Math.max(1, J.current));
            C(o.blockId, Math.min(k.end, k.start + Math.max(0, p)));
          },
          title: M,
          className: Jt("mx-px h-2.5 rounded-full", Fl[o.lane], "hover:ring-primary/40 hover:ring-2"),
          style: { gridColumn: `${k.start + 1} / ${k.end + 2}`, gridRow: 1 }
        },
        `run-${k.start}`
      )),
      o.unknownAt.map((k) => /* @__PURE__ */ m.jsx(
        "span",
        {
          "data-residency-unknown": !0,
          title: `${Rl(_.attempts[k])} · ?`,
          className: "border-muted-foreground/50 text-muted-foreground mx-0.5 flex h-2.5 items-center justify-center rounded border border-dashed text-[8px] leading-none group-data-[density=dense]/board:text-[0px]",
          style: { gridColumn: `${k + 1} / ${k + 2}`, gridRow: 1 },
          children: "?"
        },
        `unknown-${k}`
      ))
    ] })
  ] });
}
function o1({
  model: o,
  response: _,
  measure: E,
  selectedAttempt: r,
  panel: C,
  locale: J,
  t: M,
  onSelectAttempt: A,
  onSelectBlock: k,
  onSelectCompression: L
}) {
  const R = r !== null ? o.attempts[r] ?? null : null;
  return /* @__PURE__ */ m.jsx("div", { className: "min-w-0 space-y-3 rounded-md border p-3 text-sm lg:sticky lg:top-4 lg:max-h-[70vh] lg:self-start lg:overflow-y-auto", "data-residency-panel": C.mode, children: C.mode === "attempt" ? R ? /* @__PURE__ */ m.jsx(
    r1,
    {
      attempt: R,
      attemptIndex: r,
      response: _,
      model: o,
      measure: E,
      locale: J,
      t: M,
      onSelectBlock: k
    }
  ) : /* @__PURE__ */ m.jsx("p", { className: "text-muted-foreground text-xs", children: M.empty }) : C.mode === "block" ? /* @__PURE__ */ m.jsx(
    d1,
    {
      blockId: C.blockId,
      model: o,
      measure: E,
      t: M,
      onSelectAttempt: A,
      onSelectCompression: L,
      onBack: () => R ? A(r) : void 0
    }
  ) : /* @__PURE__ */ m.jsx(
    m1,
    {
      compressionId: C.compressionId,
      model: o,
      measure: E,
      locale: J,
      t: M,
      onSelectBlock: k,
      onSelectAttempt: A
    }
  ) });
}
function Ls({ crumb: o, onCrumb: _, title: E, chips: r }) {
  return /* @__PURE__ */ m.jsxs("div", { className: "space-y-1", children: [
    o && _ ? /* @__PURE__ */ m.jsxs("button", { type: "button", onClick: _, className: "text-primary text-xs underline-offset-2 hover:underline", children: [
      "‹ ",
      o
    ] }) : null,
    /* @__PURE__ */ m.jsxs("div", { className: "flex flex-wrap items-center gap-2 font-medium", children: [
      E,
      r
    ] })
  ] });
}
function r1({
  attempt: o,
  attemptIndex: _,
  response: E,
  model: r,
  measure: C,
  locale: J,
  t: M,
  onSelectBlock: A
}) {
  const [k, L] = F.useState("context"), R = Ki(o, C), p = Gs(o, E.blocks, C), U = o.status === "incomplete", X = new Map(r.rows.map((G) => [G.blockId, G]));
  return /* @__PURE__ */ m.jsxs(m.Fragment, { children: [
    /* @__PURE__ */ m.jsx(
      Ls,
      {
        title: /* @__PURE__ */ m.jsxs(m.Fragment, { children: [
          M.snapshot,
          " · ",
          Rl(o)
        ] }),
        chips: /* @__PURE__ */ m.jsxs(m.Fragment, { children: [
          o.attempt_no > 1 ? /* @__PURE__ */ m.jsx(Ji, { children: M.retryAttempt }) : null,
          /* @__PURE__ */ m.jsx(Ji, { className: Jt(U && "border-amber-500/60 text-amber-600"), children: o.status }),
          o.outcome === "failed" ? /* @__PURE__ */ m.jsx(Ji, { className: "border-destructive/60 text-destructive", children: o.outcome }) : null
        ] })
      }
    ),
    /* @__PURE__ */ m.jsxs("div", { className: "text-muted-foreground text-xs", children: [
      /* @__PURE__ */ m.jsx("code", { children: Ll(o.attempt_id) }),
      o.occurred_at ? ` · ${ki(o.occurred_at, J)}` : null,
      o.model_name ? ` · ${o.model_name}` : null,
      ` · ${o.message_count} msg · ${o.tool_schema_count} schema`
    ] }),
    /* @__PURE__ */ m.jsxs("div", { className: "text-xs", children: [
      M.total,
      ":",
      " ",
      /* @__PURE__ */ m.jsxs("span", { className: "font-mono font-medium", children: [
        ze(R, C),
        U ? `+ (${M.lowerBound})` : "",
        " ",
        C
      ] })
    ] }),
    /* @__PURE__ */ m.jsxs("div", { children: [
      /* @__PURE__ */ m.jsx("div", { className: "text-muted-foreground mb-1 text-[10px] font-semibold tracking-wide uppercase", children: M.composition }),
      /* @__PURE__ */ m.jsxs("div", { className: "flex h-3 overflow-hidden rounded", children: [
        p.map(({ lane: G, size: q }) => /* @__PURE__ */ m.jsx(
          "span",
          {
            className: Fl[G],
            style: { width: `${R > 0 ? q / R * 100 : 0}%` },
            title: `${hn(M, G)} · ${Xs(q, R)}`
          },
          G
        )),
        U ? /* @__PURE__ */ m.jsx("span", { className: "min-w-[6%] flex-1 border border-dashed bg-[repeating-linear-gradient(135deg,transparent_0_3px,var(--color-border)_3px_5px)]" }) : null
      ] }),
      /* @__PURE__ */ m.jsx("div", { className: "mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px]", children: p.map(({ lane: G, size: q }) => /* @__PURE__ */ m.jsxs("span", { className: "text-muted-foreground inline-flex items-center gap-1", children: [
        /* @__PURE__ */ m.jsx("span", { className: Jt("size-1.5 rounded-[2px]", Fl[G]) }),
        hn(M, G),
        " ",
        /* @__PURE__ */ m.jsx("b", { className: "text-foreground font-medium", children: Xs(q, R) })
      ] }, G)) })
    ] }),
    /* @__PURE__ */ m.jsxs("div", { children: [
      /* @__PURE__ */ m.jsxs("div", { className: "mb-1 flex items-center justify-between gap-2", children: [
        /* @__PURE__ */ m.jsx("div", { className: "text-muted-foreground text-[10px] font-semibold tracking-wide uppercase", children: M.members }),
        /* @__PURE__ */ m.jsx("div", { className: "flex items-center gap-0.5 rounded-md border p-0.5", children: ["context", "share"].map((G) => /* @__PURE__ */ m.jsx(
          vn,
          {
            size: "sm",
            variant: k === G ? "secondary" : "ghost",
            className: "h-5 px-1.5 text-[10px]",
            "aria-pressed": k === G,
            onClick: () => L(G),
            children: G === "context" ? M.sortContext : M.sortShare
          },
          G
        )) })
      ] }),
      /* @__PURE__ */ m.jsx("ul", { className: "space-y-0.5", "aria-label": M.members, children: u1(o.members, k, C).map((G) => {
        const q = X.get(G.block_id), at = Na(G, C);
        return /* @__PURE__ */ m.jsx("li", { children: /* @__PURE__ */ m.jsxs(
          "button",
          {
            type: "button",
            onClick: () => A(G.block_id),
            className: "hover:bg-muted/60 flex w-full items-center gap-2 rounded px-1 py-0.5 text-left text-xs",
            children: [
              /* @__PURE__ */ m.jsx("span", { className: "text-muted-foreground/70 w-5 shrink-0 text-right font-mono text-[10px]", children: G.ordinal }),
              /* @__PURE__ */ m.jsx("span", { className: Jt("size-2 shrink-0 rounded-[3px]", Fl[q?.lane ?? "unknown"]) }),
              /* @__PURE__ */ m.jsxs("span", { className: "min-w-0 flex-1 truncate", children: [
                q ? $i(M, q) : Ll(G.block_id),
                G.resolution_status === "missing" ? /* @__PURE__ */ m.jsxs("span", { className: "text-muted-foreground italic", children: [
                  " · ",
                  M.memberUnprojected
                ] }) : null
              ] }),
              /* @__PURE__ */ m.jsx("span", { className: "text-muted-foreground shrink-0 font-mono tabular-nums", children: ze(at, C) }),
              /* @__PURE__ */ m.jsx("span", { className: "w-12 shrink-0 text-right font-mono font-medium tabular-nums", children: Xs(at, R) })
            ]
          }
        ) }, `${G.ordinal}`);
      }) })
    ] }),
    U ? /* @__PURE__ */ m.jsx("p", { className: "border-l-2 border-amber-500/60 pl-2 text-[11px] text-amber-600", children: M.incompleteNote }) : null,
    r.unanchoredCompressions.length > 0 && _ === 0 ? /* @__PURE__ */ m.jsxs("p", { className: "text-muted-foreground text-[11px]", children: [
      M.unanchored,
      ": ",
      r.unanchoredCompressions.map((G) => Ll(G.compression_id)).join(", ")
    ] }) : null
  ] });
}
function d1({
  blockId: o,
  model: _,
  measure: E,
  t: r,
  onSelectAttempt: C,
  onSelectCompression: J,
  onBack: M
}) {
  const A = _.rows.find((U) => U.blockId === o);
  if (!A) return null;
  const k = _.attempts.length - 1, L = A.removedBy ? _.compressions.find((U) => U.compression_id === A.removedBy) : null, R = A.removedBy === null && A.lastSeen >= 0 && A.lastSeen < k && // Only claim a disappearance when a later COMPLETE inventory omits it.
  A.presence.slice(A.lastSeen + 1).includes("absent"), p = (U, X) => /* @__PURE__ */ m.jsx("button", { type: "button", className: "text-primary underline-offset-2 hover:underline", onClick: X, children: U });
  return /* @__PURE__ */ m.jsxs(m.Fragment, { children: [
    /* @__PURE__ */ m.jsx(
      Ls,
      {
        crumb: r.snapshot,
        onCrumb: M,
        title: /* @__PURE__ */ m.jsxs(m.Fragment, { children: [
          /* @__PURE__ */ m.jsx("span", { className: Jt("size-2.5 rounded-[3px]", Fl[A.lane]) }),
          /* @__PURE__ */ m.jsx("span", { className: "min-w-0 truncate", children: $i(r, A) })
        ] })
      }
    ),
    /* @__PURE__ */ m.jsxs("div", { className: "text-muted-foreground text-xs", children: [
      hn(r, A.lane),
      " · ",
      /* @__PURE__ */ m.jsx("code", { children: Ll(A.blockId) }),
      A.meta?.content_hash ? /* @__PURE__ */ m.jsxs(m.Fragment, { children: [
        " ",
        "· ",
        /* @__PURE__ */ m.jsx("code", { title: A.meta.content_hash, children: A.meta.content_hash.slice(0, 10) })
      ] }) : null,
      ` · ${ze(Na({ estimated_tokens: A.sizeTokens, visible_bytes: A.sizeBytes }, E), E)} ${E}`
    ] }),
    /* @__PURE__ */ m.jsxs("div", { children: [
      /* @__PURE__ */ m.jsxs("div", { className: "text-muted-foreground mb-1 text-[10px] font-semibold tracking-wide uppercase", children: [
        r.residence,
        " · ",
        _.attempts.length,
        " attempts"
      ] }),
      /* @__PURE__ */ m.jsx("div", { className: "flex gap-px", children: A.presence.map((U, X) => /* @__PURE__ */ m.jsx(
        "button",
        {
          type: "button",
          onClick: () => C(X),
          title: `${Rl(_.attempts[X])} · ${U}`,
          className: Jt(
            "h-2.5 min-w-0.5 flex-1 rounded-[1px]",
            U === "present" && Fl[A.lane],
            U === "absent" && "bg-muted",
            U === "unknown" && "border-muted-foreground/50 border border-dashed bg-transparent"
          )
        },
        X
      )) }),
      /* @__PURE__ */ m.jsxs("div", { className: "text-muted-foreground mt-0.5 flex justify-between text-[10px]", children: [
        /* @__PURE__ */ m.jsx("span", { children: _.attempts[0] ? Rl(_.attempts[0]) : "" }),
        /* @__PURE__ */ m.jsx("span", { children: _.attempts[k] ? Rl(_.attempts[k]) : "" })
      ] })
    ] }),
    /* @__PURE__ */ m.jsxs("dl", { className: "space-y-1.5 text-xs", children: [
      A.firstSeen >= 0 ? /* @__PURE__ */ m.jsxs("div", { children: [
        /* @__PURE__ */ m.jsxs("dt", { className: "text-muted-foreground inline", children: [
          r.firstSeen,
          ": "
        ] }),
        /* @__PURE__ */ m.jsx("dd", { className: "inline", children: p(Rl(_.attempts[A.firstSeen]), () => C(A.firstSeen)) })
      ] }) : null,
      L ? /* @__PURE__ */ m.jsxs("div", { children: [
        /* @__PURE__ */ m.jsxs("dt", { className: "text-muted-foreground inline", children: [
          r.removedBy,
          ": "
        ] }),
        /* @__PURE__ */ m.jsxs("dd", { className: "inline", children: [
          p(Ll(L.compression_id), () => J(L.compression_id)),
          L.summary_block_id ? /* @__PURE__ */ m.jsxs(m.Fragment, { children: [
            " ",
            /* @__PURE__ */ m.jsxs("span", { className: "text-muted-foreground", children: [
              "→ ",
              r.continuesIn,
              " "
            ] }),
            p(Ll(L.summary_block_id), () => J(L.compression_id))
          ] }) : null
        ] })
      ] }) : R ? /* @__PURE__ */ m.jsxs("div", { children: [
        /* @__PURE__ */ m.jsxs("dt", { className: "text-muted-foreground inline", children: [
          r.lastSeen,
          ": "
        ] }),
        /* @__PURE__ */ m.jsxs("dd", { className: "inline", children: [
          p(Rl(_.attempts[A.lastSeen]), () => C(A.lastSeen)),
          " ",
          /* @__PURE__ */ m.jsxs("span", { className: "text-muted-foreground", children: [
            "· ",
            r.removalUnrecorded
          ] })
        ] })
      ] }) : /* @__PURE__ */ m.jsx("div", { children: /* @__PURE__ */ m.jsx("dd", { className: "text-muted-foreground", children: r.stillPresent }) }),
      A.preservedBy.length > 0 ? /* @__PURE__ */ m.jsxs("div", { children: [
        /* @__PURE__ */ m.jsxs("dt", { className: "text-muted-foreground inline", children: [
          r.preservedBy,
          ": "
        ] }),
        /* @__PURE__ */ m.jsx("dd", { className: "inline", children: A.preservedBy.map((U, X) => /* @__PURE__ */ m.jsxs("span", { children: [
          X > 0 ? ", " : null,
          p(Ll(U), () => J(U))
        ] }, U)) })
      ] }) : null,
      A.summaryOf ? /* @__PURE__ */ m.jsxs("div", { children: [
        /* @__PURE__ */ m.jsxs("dt", { className: "text-muted-foreground inline", children: [
          r.summaryOf,
          ": "
        ] }),
        /* @__PURE__ */ m.jsx("dd", { className: "inline", children: p(Ll(A.summaryOf), () => J(A.summaryOf)) })
      ] }) : null
    ] })
  ] });
}
function m1({
  compressionId: o,
  model: _,
  measure: E,
  locale: r,
  t: C,
  onSelectBlock: J,
  onSelectAttempt: M
}) {
  const A = _.compressions.find((R) => R.compression_id === o);
  if (!A) return null;
  const k = A.positioned_before_attempt_id ? _.attempts.findIndex((R) => R.attempt_id === A.positioned_before_attempt_id) : -1, L = (R) => {
    const p = _.rows.find((U) => U.blockId === R);
    return /* @__PURE__ */ m.jsx("li", { children: /* @__PURE__ */ m.jsxs(
      "button",
      {
        type: "button",
        onClick: () => J(R),
        className: "hover:bg-muted/60 flex w-full items-center gap-2 rounded px-1 py-0.5 text-left text-xs",
        children: [
          /* @__PURE__ */ m.jsx("span", { className: Jt("size-2 shrink-0 rounded-[3px]", Fl[p?.lane ?? "unknown"]) }),
          /* @__PURE__ */ m.jsx("span", { className: "min-w-0 flex-1 truncate", children: p ? $i(C, p) : Ll(R) }),
          p ? /* @__PURE__ */ m.jsx("span", { className: "text-muted-foreground shrink-0 font-mono text-[10px] tabular-nums", children: ze(Na({ estimated_tokens: p.sizeTokens, visible_bytes: p.sizeBytes }, E), E) }) : null
        ]
      }
    ) }, R);
  };
  return /* @__PURE__ */ m.jsxs(m.Fragment, { children: [
    /* @__PURE__ */ m.jsx(
      Ls,
      {
        title: /* @__PURE__ */ m.jsxs(m.Fragment, { children: [
          /* @__PURE__ */ m.jsx(j0, { className: "size-3.5 text-purple-600" }),
          C.compression,
          " ",
          Ll(A.compression_id)
        ] }),
        chips: k < 0 ? /* @__PURE__ */ m.jsx(Ji, { className: "border-amber-500/60 text-amber-600", children: A.status }) : null
      }
    ),
    /* @__PURE__ */ m.jsxs("div", { className: "text-muted-foreground text-xs", children: [
      A.occurred_at ? ki(A.occurred_at, r) : null,
      k >= 0 ? /* @__PURE__ */ m.jsxs(m.Fragment, { children: [
        " · ",
        C.positionedBefore,
        " ",
        /* @__PURE__ */ m.jsx("button", { type: "button", className: "text-primary underline-offset-2 hover:underline", onClick: () => M(k), children: Rl(_.attempts[k]) })
      ] }) : /* @__PURE__ */ m.jsxs(m.Fragment, { children: [
        " · ",
        C.unanchored
      ] })
    ] }),
    /* @__PURE__ */ m.jsxs("div", { className: "text-xs", children: [
      C.compressionScope,
      ":",
      " ",
      /* @__PURE__ */ m.jsxs("span", { className: "font-mono", children: [
        ze(A.before_tokens, "tokens"),
        " → ",
        ze(A.after_tokens, "tokens"),
        " tokens"
      ] })
    ] }),
    /* @__PURE__ */ m.jsxs("div", { children: [
      /* @__PURE__ */ m.jsxs("div", { className: "text-muted-foreground mb-1 text-[10px] font-semibold tracking-wide uppercase", children: [
        C.removed,
        " · ",
        A.removed_block_ids.length
      ] }),
      /* @__PURE__ */ m.jsx("ul", { className: "space-y-0.5", children: A.removed_block_ids.map((R) => L(R)) })
    ] }),
    A.preserved_block_ids.length > 0 ? /* @__PURE__ */ m.jsxs("div", { children: [
      /* @__PURE__ */ m.jsxs("div", { className: "text-muted-foreground mb-1 text-[10px] font-semibold tracking-wide uppercase", children: [
        C.preserved,
        " · ",
        A.preserved_block_ids.length
      ] }),
      /* @__PURE__ */ m.jsx("ul", { className: "space-y-0.5", children: A.preserved_block_ids.map((R) => L(R)) })
    ] }) : null,
    /* @__PURE__ */ m.jsxs("div", { children: [
      /* @__PURE__ */ m.jsx("div", { className: "text-muted-foreground mb-1 text-[10px] font-semibold tracking-wide uppercase", children: C.summaryBlock }),
      A.summary_block_id ? /* @__PURE__ */ m.jsx("ul", { children: L(A.summary_block_id) }) : /* @__PURE__ */ m.jsx("p", { className: "text-muted-foreground text-xs", children: C.summaryBlockUnknown })
    ] })
  ] });
}
function A0(o, _) {
  return o instanceof C0 ? `${_} (${o.status}: ${o.message})` : o instanceof Error ? `${_} (${o.message})` : _;
}
function v1(o, _) {
  const E = new URL(window.location.href);
  o ? E.searchParams.set("thread", o) : E.searchParams.delete("thread"), _ ? E.searchParams.set("task", _) : E.searchParams.delete("task"), window.history.replaceState(window.history.state, "", E);
}
function h1({ base: o, locale: _, signal: E, initialThreadId: r, initialTaskId: C, initialStepSeq: J }) {
  const M = F.useMemo(() => e1(_), [_]), [A, k] = F.useState(r), [L, R] = F.useState(C), [p, U] = F.useState(r ?? ""), [X, G] = F.useState(C ?? ""), [q, at] = F.useState({ status: "idle" }), [Ot, ht] = F.useState({ status: "idle" }), [Pt, St] = F.useState(!1), Mt = F.useCallback(
    async ($) => {
      at({ status: "loading" });
      try {
        const _t = await Zy(o, $, E);
        return at({ status: "ready", data: _t.tasks }), _t.tasks;
      } catch (_t) {
        return E.aborted ? [] : (at({ status: "error", message: A0(_t, M.loadFailed) }), []);
      }
    },
    [o, E, M.loadFailed]
  ), pt = F.useCallback(
    async ($, _t = !1) => {
      _t ? St(!0) : ht({ status: "loading" });
      try {
        const gt = await Ly(o, $, E);
        ht({ status: "ready", data: gt });
      } catch (gt) {
        if (E.aborted) return;
        ht({ status: "error", message: A0(gt, M.loadFailed) });
      } finally {
        St(!1);
      }
    },
    [o, E, M.loadFailed]
  );
  F.useEffect(() => {
    (async () => {
      if (A) {
        const $ = await Mt(A);
        if (!L && $.length > 0) {
          const _t = $.find((gt) => gt.kind === "lead") ?? $[0];
          R(_t.task_id), G(_t.task_id);
        }
      }
    })();
  }, []), F.useEffect(() => {
    v1(A, L), L ? pt(L) : ht({ status: "idle" });
  }, [L, A, pt]);
  const ut = F.useCallback(() => {
    const $ = p.trim();
    k($ || null), R(null), G(""), $ ? Mt($).then((_t) => {
      const gt = _t.find((qt) => qt.kind === "lead") ?? _t[0];
      gt && (R(gt.task_id), G(gt.task_id));
    }) : at({ status: "idle" });
  }, [Mt, p]), lt = F.useCallback(() => {
    const $ = X.trim();
    R($ || null);
  }, [X]), Ht = Ot.status === "ready" ? Ot.data.projection_status : null;
  return /* @__PURE__ */ m.jsxs("div", { className: "space-y-4", "data-residency-app": !0, children: [
    /* @__PURE__ */ m.jsxs(
      "form",
      {
        className: "flex flex-wrap items-end gap-3 text-xs",
        onSubmit: ($) => {
          $.preventDefault(), ut();
        },
        children: [
          /* @__PURE__ */ m.jsxs("label", { className: "flex flex-col gap-1", children: [
            /* @__PURE__ */ m.jsx("span", { className: "text-muted-foreground", children: M.threadLabel }),
            /* @__PURE__ */ m.jsx(
              "input",
              {
                className: "bg-background h-8 w-72 rounded-md border px-2 font-mono",
                value: p,
                onChange: ($) => U($.target.value),
                spellCheck: !1
              }
            )
          ] }),
          /* @__PURE__ */ m.jsx(vn, { size: "sm", type: "submit", children: M.load }),
          /* @__PURE__ */ m.jsxs("label", { className: "flex flex-col gap-1", children: [
            /* @__PURE__ */ m.jsx("span", { className: "text-muted-foreground", children: M.taskLabel }),
            /* @__PURE__ */ m.jsx(
              "input",
              {
                className: "bg-background h-8 w-72 rounded-md border px-2 font-mono",
                value: X,
                onChange: ($) => G($.target.value),
                onKeyDown: ($) => {
                  $.key === "Enter" && ($.preventDefault(), lt());
                },
                spellCheck: !1
              }
            )
          ] }),
          /* @__PURE__ */ m.jsx(vn, { size: "sm", onClick: lt, children: M.load })
        ]
      }
    ),
    q.status === "loading" ? /* @__PURE__ */ m.jsx(N0, { className: "h-8 w-full" }) : null,
    q.status === "error" ? /* @__PURE__ */ m.jsx("p", { className: "text-destructive text-xs", children: q.message }) : null,
    q.status === "ready" ? /* @__PURE__ */ m.jsxs("div", { className: "space-y-1", children: [
      /* @__PURE__ */ m.jsx("div", { className: "text-muted-foreground text-[10px] font-semibold tracking-wide uppercase", children: M.tasks }),
      q.data.length === 0 ? /* @__PURE__ */ m.jsx("p", { className: "text-muted-foreground text-xs", children: M.noTasks }) : /* @__PURE__ */ m.jsx("ul", { className: "flex flex-wrap gap-1.5", "data-residency-tasks": !0, children: q.data.map(($) => /* @__PURE__ */ m.jsx("li", { children: /* @__PURE__ */ m.jsxs(
        "button",
        {
          type: "button",
          "aria-pressed": $.task_id === L,
          onClick: () => {
            R($.task_id), G($.task_id);
          },
          title: `${$.task_id} · ${ki($.started_at, _)}`,
          className: $.task_id === L ? "bg-primary text-primary-foreground rounded-full border px-2 py-0.5 text-xs" : "hover:bg-muted rounded-full border px-2 py-0.5 text-xs",
          children: [
            $.kind === "lead" ? M.taskKindLead : M.taskKindSubagent,
            $.agent_name ? ` · ${$.agent_name}` : "",
            " · ",
            /* @__PURE__ */ m.jsx("span", { className: "font-mono", children: Ll($.task_id) }),
            $.outcome ? ` · ${$.outcome}` : ""
          ]
        }
      ) }, $.task_id)) })
    ] }) : null,
    Ht && !Ht.running ? /* @__PURE__ */ m.jsx("p", { className: "text-xs text-amber-600", children: M.recordingOff }) : null,
    Ht && Ht.dropped > 0 ? /* @__PURE__ */ m.jsx("p", { className: "text-xs text-amber-600", children: M.dropped(Ht.dropped) }) : null,
    Ot.status === "loading" ? /* @__PURE__ */ m.jsx(N0, { className: "h-64 w-full" }) : null,
    Ot.status === "error" ? /* @__PURE__ */ m.jsx("p", { className: "text-destructive rounded-md border p-3 text-sm", children: Ot.message }) : null,
    Ot.status === "ready" && L ? /* @__PURE__ */ m.jsx(
      f1,
      {
        response: Ot.data,
        locale: _,
        t: M,
        refreshing: Pt,
        onRefresh: () => {
          pt(L, !0);
        },
        seedStepSeq: J
      },
      L
    ) : null
  ] });
}
const y1 = "community.context-residency", M0 = "board";
function g1() {
  const o = new URLSearchParams(window.location.search), _ = o.get("step"), E = _ !== null && /^\d+$/.test(_) ? Number(_) : null;
  return { threadId: o.get("thread"), taskId: o.get("task"), stepSeq: E };
}
function b1() {
  const o = ["styles", "css"].join(".");
  return new URL(o, import.meta.url).href;
}
function S1(o, _) {
  const E = document.createElement("link");
  E.rel = "stylesheet", E.crossOrigin = "use-credentials", E.href = b1();
  const r = document.createElement("div");
  o.append(E, r);
  const C = g1(), J = Gy.createRoot(r);
  return J.render(
    F.createElement(h1, {
      base: Qy(import.meta.url),
      locale: _.locale,
      signal: _.signal,
      initialThreadId: C.threadId ?? _.threadId ?? null,
      initialTaskId: C.taskId,
      initialStepSeq: C.stepSeq
    })
  ), {
    dispose() {
      J.unmount(), E.remove(), r.remove();
    }
  };
}
const p1 = {
  apiVersion: 1,
  module: "context-residency.v1",
  icon: "layers",
  surfaces: [
    {
      id: M0,
      slot: "page",
      title: "Context residency",
      navigation: { label: "Context residency", labelZh: "上下文留存", icon: "layers" },
      mount: S1
    }
  ],
  conversationActions(o, _ = "en") {
    const E = _.startsWith("zh");
    return {
      label: E ? "上下文留存" : "Context residency",
      icon: "layers",
      actions: [
        {
          id: "open-residency",
          label: E ? "查看这个会话的上下文留存" : "Open context residency for this conversation",
          icon: "layers",
          available: (r) => r.enabled === !0,
          async execute(r) {
            const C = new URL(`/workspace/extensions/${encodeURIComponent(y1)}/${M0}`, window.location.origin);
            C.searchParams.set("thread", r.thread.thread_id), window.location.assign(C.toString());
          }
        }
      ]
    };
  }
};
export {
  p1 as default
};
